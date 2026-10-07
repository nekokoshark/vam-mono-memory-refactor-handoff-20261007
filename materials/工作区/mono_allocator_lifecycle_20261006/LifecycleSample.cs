using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Threading;

public sealed class LifecycleCell { public long Id; public long Value; }

public static class LifecycleSample
{
    const int Count = 1024 * 1024;
    static LifecycleCell[] all, keep, refill;
    static long[] rootAddresses;
    static byte[] large, replacement;
    static GCHandle pinned;
    static IntPtr pinnedAddress;
    static int pageCount;
    static byte[][] sectionFragments, sectionPayload;
    static int sectionCount;

    static void Worker(ThreadStart work)
    {
        Exception error = null;
        Thread t = new Thread(delegate() { try { work(); } catch (Exception e) { error = e; } });
        t.Start(); t.Join();
        if (error != null) throw error;
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    public static string PrepareCells()
    {
        Worker(delegate {
            all = new LifecycleCell[Count];
            for (int i = 0; i < Count; i++) all[i] = new LifecycleCell { Id = i, Value = i ^ 0x5a5a5a };
            List<LifecycleCell> roots = new List<LifecycleCell>();
            Dictionary<long, int> seen = new Dictionary<long, int>();
            GCHandle handle = GCHandle.Alloc(all, GCHandleType.Pinned);
            try {
                IntPtr slots = handle.AddrOfPinnedObject();
                for (int i = 0; i < Count; i++) {
                    long page = Marshal.ReadIntPtr(slots, i * IntPtr.Size).ToInt64() & ~4095L;
                    int used;
                    if (!seen.TryGetValue(page, out used)) used = 0;
                    int limit = (int)((page >> 12) & 3);
                    limit = limit == 0 ? 1 : limit == 1 ? 16 : limit == 2 ? 48 : 80;
                    if (used < limit) roots.Add(all[i]);
                    seen[page] = used + 1;
                }
                pageCount = seen.Count;
            } finally { handle.Free(); }
            keep = roots.ToArray();
            rootAddresses = new long[keep.Length];
            GCHandle rootsPin = GCHandle.Alloc(keep, GCHandleType.Pinned);
            try {
                IntPtr slots = rootsPin.AddrOfPinnedObject();
                for (int i = 0; i < keep.Length; i++)
                    rootAddresses[i] = Marshal.ReadIntPtr(slots, i * IntPtr.Size).ToInt64();
            } finally { rootsPin.Free(); }
        });
        return "CELLS_PREPARED count=" + Count + " pages=" + pageCount + " roots=" + keep.Length;
    }

    public static string DropCells() { Worker(delegate { all = null; }); return "CELLS_DROPPED originals=null"; }
    public static string RefillCells()
    {
        Worker(delegate {
            refill = new LifecycleCell[262144];
            for (int i = 0; i < refill.Length; i++)
                refill[i] = new LifecycleCell { Id = Count + i, Value = (Count + i) ^ 0x5a5a5a };
        });
        return CheckCells();
    }

    public static string CheckCells()
    {
        foreach (LifecycleCell x in keep)
            if (x.Value != (x.Id ^ 0x5a5a5a)) throw new Exception("Rooted cell changed");
        if (refill != null) foreach (LifecycleCell x in refill)
            if (x.Value != (x.Id ^ 0x5a5a5a)) throw new Exception("Reused cell changed");
        GCHandle rootsPin = GCHandle.Alloc(keep, GCHandleType.Pinned);
        try {
            IntPtr slots = rootsPin.AddrOfPinnedObject();
            for (int i = 0; i < keep.Length; i++)
                if (rootAddresses[i] != Marshal.ReadIntPtr(slots, i * IntPtr.Size).ToInt64())
                    throw new Exception("Rooted cell address changed");
        } finally { rootsPin.Free(); }
        return "CELLS_OK aliases=preserved roots=" + keep.Length + " refill=" + (refill == null ? 0 : refill.Length);
    }

    public static string DropCellRoots()
    {
        Worker(delegate { keep = refill = null; rootAddresses = null; });
        return "CELL_ROOTS_DROPPED roots=null aliases=null";
    }

    static void Touch(byte[] x)
    {
        for (int i = 0; i < x.Length; i += 4096) x[i] = (byte)(i / 4096 * 17 + 19);
        x[x.Length - 1] = 213;
    }
    static void Check(byte[] x)
    {
        for (int i = 0; i < x.Length; i += 4096)
            if (x[i] != (byte)(i / 4096 * 17 + 19)) throw new Exception("Page contents changed");
        if (x[x.Length - 1] != 213) throw new Exception("Last byte changed");
    }
    public static string PrepareLarge()
    {
        Worker(delegate { large = new byte[768 * 1024 * 1024]; Touch(large); });
        return "LARGE_PREPARED bytes=805306368 pageTouched=True";
    }
    public static string DropLarge() { Worker(delegate { large = null; }); return "LARGE_DROPPED root=null"; }
    public static string ReplaceLarge()
    {
        Worker(delegate {
            replacement = new byte[300 * 1024 * 1024]; Touch(replacement);
            pinned = GCHandle.Alloc(replacement, GCHandleType.Pinned);
            pinnedAddress = pinned.AddrOfPinnedObject();
        });
        return CheckLarge();
    }
    public static string CheckLarge()
    {
        Check(replacement);
        if (pinned.AddrOfPinnedObject() != pinnedAddress) throw new Exception("Pinned address changed");
        return "PREFIX_OK bytes=314572800 pinnedAddress=preserved pixels=verified";
    }
    public static string DropReplacement()
    {
        Worker(delegate { pinned.Free(); replacement = null; });
        return "PREFIX_DROPPED pin=freed root=null";
    }
    public static string AllocationFailure()
    {
        bool caught = false;
        Worker(delegate {
            try {
                byte[] demand = new byte[64 * 1024 * 1024];
                GC.KeepAlive(demand);
            } catch (OutOfMemoryException) { caught = true; }
        });
        if (!caught) throw new Exception("Original maximum heap check was bypassed");
        return "OOM_OK originalException=caught";
    }
    public static string AfterFailure()
    {
        Worker(delegate { byte[] x = new byte[1024 * 1024]; Touch(x); Check(x); });
        return "AFTER_OOM_OK allocation=restored data=verified";
    }

    public static string PrepareSectionFragments()
    {
        Worker(delegate {
            sectionFragments = new byte[8192][];
            for (int i = 0; i < sectionFragments.Length; i++) {
                byte[] x = new byte[8192];
                Touch(x);
                sectionFragments[i] = x;
            }
            sectionPayload = new byte[50000][];
            sectionCount = 0;
        });
        return "SECTION_FRAGMENTS count=8192 bytesEach=8192";
    }

    public static string DropSectionFragments()
    {
        Worker(delegate {
            for (int i = 0; i < sectionFragments.Length; i += 2)
                sectionFragments[i] = null;
        });
        return "SECTION_HOLES freed=4096 retained=4096";
    }

    public static string AddSectionBatch()
    {
        Worker(delegate {
            int end = Math.Min(sectionCount + 128, sectionPayload.Length);
            while (sectionCount < end) {
                byte[] x = new byte[16384];
                Touch(x);
                sectionPayload[sectionCount++] = x;
            }
        });
        return "SECTION_ADDED count=" + sectionCount;
    }

    public static string CheckSections()
    {
        foreach (byte[] x in sectionFragments) if (x != null) Check(x);
        for (int i = 0; i < sectionCount; i++) Check(sectionPayload[i]);
        return "SECTION_CONTENT_OK retained=" + sectionCount;
    }
}
