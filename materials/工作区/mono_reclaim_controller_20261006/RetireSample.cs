using System;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Threading;

public static class RetireSample
{
    static byte[][] live;
    static byte[][] temporary;
    static WeakReference retired;
    static GCHandle pinned;
    static IntPtr pinnedAddress;
    const int BlockBytes = 8 * 1024 * 1024;
    const int Blocks = 64;

    static byte Pattern(int block, int page)
    {
        return (byte)((block * 17 + page * 3 + 19) % 251);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    static byte[][] Allocate(int count)
    {
        byte[][] result = new byte[count][];
        for (int block = 0; block < count; block++)
        {
            byte[] value = new byte[BlockBytes];
            for (int page = 0; page < BlockBytes / 4096; page++)
                value[page * 4096] = Pattern(block, page);
            result[block] = value;
        }
        return result;
    }

    static void Check(byte[][] arrays)
    {
        for (int block = 0; block < arrays.Length; block++)
            for (int page = 0; page < BlockBytes / 4096; page++)
                if (arrays[block][page * 4096] != Pattern(block, page))
                    throw new Exception("Live/reused page content changed");
        if (pinned.IsAllocated && pinned.AddrOfPinnedObject() != pinnedAddress)
            throw new Exception("Pinned live array changed address");
    }

    static void Worker(ThreadStart action)
    {
        Thread thread = new Thread(action);
        thread.Start();
        thread.Join();
    }

    public static string Prepare()
    {
        Worker(delegate {
            live = Allocate(4);
            pinned = GCHandle.Alloc(live[0], GCHandleType.Pinned);
            pinnedAddress = pinned.AddrOfPinnedObject();
            temporary = Allocate(Blocks);
            Check(live);
            Check(temporary);
        });
        return "PREPARE live=33554432 temporary=536870912 touchedEveryPage=True";
    }

    public static string Drop()
    {
        Worker(delegate {
            retired = new WeakReference(temporary);
            temporary = null;
        });
        return "DROP temporaryRoot=null";
    }

    public static string CheckLive()
    {
        Check(live);
        return "CHECK_LIVE_OK retiredContainerAlive=" + retired.IsAlive;
    }

    public static string Reuse()
    {
        Worker(delegate {
            temporary = Allocate(Blocks);
            Check(temporary);
            Check(live);
        });
        return "REUSE_OK liveAndNewPages=verified";
    }

    public static string Concurrent()
    {
        const int Workers = 4;
        const int Rounds = 32;
        ManualResetEvent start = new ManualResetEvent(false);
        Thread[] workers = new Thread[Workers];
        Exception[] errors = new Exception[Workers + 1];
        for (int id = 0; id < Workers; id++)
        {
            int worker = id;
            workers[id] = new Thread(delegate() {
                try {
                    start.WaitOne();
                    for (int round = 0; round < Rounds; round++)
                    {
                        int size = round % 2 == 0 ? 2 * 1024 * 1024 : 17 * 1024 + worker;
                        byte[] value = new byte[size];
                        byte expected = Pattern(worker, round);
                        for (int offset = 0; offset < size; offset += 4096)
                            value[offset] = expected;
                        Thread.Sleep(1);
                        for (int offset = 0; offset < size; offset += 4096)
                            if (value[offset] != expected)
                                throw new Exception("Concurrent live page changed");
                        GC.KeepAlive(value);
                    }
                } catch (Exception error) { errors[worker] = error; }
            });
            workers[id].Start();
        }
        Thread collector = new Thread(delegate() {
            try {
                start.WaitOne();
                for (int round = 0; round < 16; round++)
                {
                    GC.Collect();
                    Check(live);
                    Thread.Sleep(1);
                }
            } catch (Exception error) { errors[Workers] = error; }
        });
        collector.Start();
        start.Set();
        foreach (Thread thread in workers) thread.Join();
        collector.Join();
        start.Close();
        foreach (Exception error in errors)
            if (error != null) throw error;
        Check(live);
        return "CONCURRENT_OK workers=4 rounds=32 pinnedLive=verified";
    }

    public static string Mixed()
    {
        Worker(delegate {
            for (int round = 0; round < 8; round++) {
                byte[][] bytes = new byte[512][];
                string[] strings = new string[4096];
                int[][] indices = new int[512][];
                object[] references = new object[512];
                for (int n = 0; n < bytes.Length; n++) {
                    bytes[n] = new byte[4096 + n * 17];
                    bytes[n][bytes[n].Length - 1] = (byte)n;
                    indices[n] = new int[1024 + n];
                    indices[n][0] = n;
                    references[n] = indices[n];
                }
                for (int n = 0; n < strings.Length; n++)
                    strings[n] = new string((char)(33 + n % 90), 31 + n % 128);
                GC.Collect();
                for (int n = 0; n < bytes.Length; n++) {
                    if (bytes[n][bytes[n].Length - 1] != (byte)n ||
                        indices[n][0] != n || !Object.ReferenceEquals(references[n], indices[n]))
                        throw new Exception("Mixed live payload/alias changed");
                }
                for (int n = 0; n < strings.Length; n++)
                    if (strings[n][0] != (char)(33 + n % 90) || strings[n].Length != 31 + n % 128)
                        throw new Exception("Mixed live string changed");
                Check(live);
                GC.KeepAlive(references);
            }
        });
        return "MIXED_OK rounds=8 arrays=strings+references+bytes+indices aliases=preserved";
    }

    public static string Exceptions()
    {
        Worker(delegate {
            for (int n = 0; n < 25000; n++) {
                using (System.IO.StringReader reader = new System.IO.StringReader("sentinel")) {
                    if (reader.ReadLine() != "sentinel") throw new Exception("Reader changed");
                }
                if (n % 100 == 0) {
                    try { throw new InvalidOperationException("exception-sentinel"); }
                    catch (InvalidOperationException error) {
                        if (error.Message != "exception-sentinel") throw;
                    }
                }
                if (n % 1000 == 0) GC.Collect();
            }
            Check(live);
        });
        return "EXCEPTIONS_OK dispose=25000 exceptions=250 pinnedLive=verified";
    }

    public static string Fragmented()
    {
        Worker(delegate {
            for (int round = 0; round < 4; round++) {
                byte[][] small = new byte[16384][];
                byte[][] large = new byte[8192][];
                for (int n = 0; n < small.Length; n++) {
                    small[n] = new byte[127 + n % 40];
                    small[n][0] = (byte)n;
                    small[n][small[n].Length - 1] = (byte)(n + 1);
                }
                for (int n = 0; n < large.Length; n++) {
                    large[n] = new byte[4097 + n % 107];
                    large[n][0] = (byte)n;
                    large[n][large[n].Length - 1] = (byte)(n + 1);
                }
                for (int n = 0; n < small.Length; n += 2) small[n] = null;
                for (int n = 0; n < large.Length; n += 2) large[n] = null;
                GC.Collect();
                for (int n = 1; n < small.Length; n += 2)
                    if (small[n][0] != (byte)n || small[n][small[n].Length - 1] != (byte)(n + 1))
                        throw new Exception("Partial small-object page corrupted");
                for (int n = 1; n < large.Length; n += 2)
                    if (large[n][0] != (byte)n || large[n][large[n].Length - 1] != (byte)(n + 1))
                        throw new Exception("Interleaved large-object page corrupted");
                Check(live);
                GC.KeepAlive(small);
                GC.KeepAlive(large);
            }
        });
        return "FRAGMENTED_OK rounds=4 liveSmall=8192 liveLarge=4096 pinnedLive=verified";
    }
}
