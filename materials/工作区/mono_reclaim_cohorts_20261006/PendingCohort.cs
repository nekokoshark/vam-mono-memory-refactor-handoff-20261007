using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Threading;

// Real managed objects in a separate embedded-Mono process, never the game.
public sealed class OtherCell { public long Id, Value, Extra1, Extra2; }

public static class PendingCohort
{
    const int Count = 2200000;
    static byte[][] all, keep;
    static long[] addresses;
    static OtherCell[] otherAll, otherKeep;

    static void Worker(ThreadStart action)
    {
        Exception error = null;
        Thread t = new Thread(delegate() { try { action(); } catch (Exception e) { error = e; } });
        t.Start(); t.Join();
        if (error != null) throw error;
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    public static string Prepare()
    {
        Worker(delegate {
            all = new byte[Count][];
            keep = new byte[Count / 2][];
            for (int i = 0; i < Count; ++i) {
                byte[] x = new byte[1536];
                x[0] = 71; x[1535] = 193;
                all[i] = x;
                if ((i & 1) == 0) keep[i / 2] = x;
            }
            addresses = new long[keep.Length];
            GCHandle pin = GCHandle.Alloc(keep, GCHandleType.Pinned);
            try {
                IntPtr slots = pin.AddrOfPinnedObject();
                for (int i = 0; i < keep.Length; ++i)
                    addresses[i] = Marshal.ReadIntPtr(slots, i * IntPtr.Size).ToInt64();
            } finally { pin.Free(); }
        });
        return "COHORT_PREPARED objects=2200000 roots=1100000 bytesEach=1536";
    }

    public static string Drop() { Worker(delegate { all = null; }); return "COHORT_DROPPED originals=null"; }

    public static string Check()
    {
        GCHandle pin = GCHandle.Alloc(keep, GCHandleType.Pinned);
        try {
            IntPtr slots = pin.AddrOfPinnedObject();
            for (int i = 0; i < keep.Length; ++i) {
                if (keep[i][0] != 71 || keep[i][1535] != 193)
                    throw new Exception("Rooted array content changed");
                if (addresses[i] != Marshal.ReadIntPtr(slots, i * IntPtr.Size).ToInt64())
                    throw new Exception("Rooted array address changed");
            }
        } finally { pin.Free(); }
        return "COHORT_OK roots=1100000 aliases=preserved bytes=verified";
    }

    public static string Release()
    {
        Worker(delegate { all = keep = null; addresses = null; });
        return "COHORT_RELEASED roots=null";
    }

    public static string PrepareOther()
    {
        Worker(delegate {
            otherAll = new OtherCell[196608];
            for (int i = 0; i < otherAll.Length; ++i)
                otherAll[i] = new OtherCell { Id = i, Value = i ^ 0x3a3a3a, Extra1 = 7, Extra2 = 19 };
            List<OtherCell> roots = new List<OtherCell>();
            GCHandle pin = GCHandle.Alloc(otherAll, GCHandleType.Pinned);
            try {
                long last = -1; int used = 0;
                IntPtr slots = pin.AddrOfPinnedObject();
                for (int i = 0; i < otherAll.Length; ++i) {
                    long page = Marshal.ReadIntPtr(slots, i * IntPtr.Size).ToInt64() & ~4095L;
                    if (page != last) { last = page; used = 0; }
                    int band = (int)((page >> 12) & 3);
                    int limit = band == 0 ? 8 : band == 1 ? 24 : band == 2 ? 56 : 80;
                    if (used++ < limit) roots.Add(otherAll[i]);
                }
            } finally { pin.Free(); }
            otherKeep = roots.ToArray();
        });
        return "OTHER_PREPARED cells=196608";
    }

    public static string DropOther() { Worker(delegate { otherAll = null; }); return "OTHER_DROPPED originals=null"; }
    public static string CheckOther()
    {
        foreach (OtherCell x in otherKeep)
            if (x.Value != (x.Id ^ 0x3a3a3a) || x.Extra1 != 7 || x.Extra2 != 19)
                throw new Exception("Other rooted cell changed");
        return "OTHER_OK roots=" + otherKeep.Length;
    }
    public static string ReleaseOther() { Worker(delegate { otherAll = otherKeep = null; }); return "OTHER_RELEASED roots=null"; }
}
