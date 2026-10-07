using System;

public static class WarmPages
{
    static byte[][] seed;
    static byte[][] cells;
    static byte[] alias;
    const int Count = 524288;

    public static string Seed()
    {
        seed = new byte[16][];
        for (int i = 0; i < seed.Length; ++i)
        {
            seed[i] = new byte[64 * 1024 * 1024];
            seed[i][0] = (byte)i;
            seed[i][seed[i].Length - 1] = (byte)(i + 1);
        }
        return "SEED_OK bytes=1073741824";
    }

    public static string Drop()
    {
        seed = null;
        cells = null;
        alias = null;
        return "DROP_OK roots=removed";
    }

    public static string Allocate()
    {
        cells = new byte[Count][];
        for (int i = 0; i < Count; ++i)
        {
            byte[] x = new byte[1000];
            x[0] = (byte)i;
            x[999] = (byte)(i >> 8);
            cells[i] = x;
        }
        alias = cells[Count / 2];
        return Check();
    }

    public static string Check()
    {
        if (cells == null || cells.Length != Count ||
            !Object.ReferenceEquals(alias, cells[Count / 2]))
            throw new Exception("Lost cells or alias");
        for (int i = 0; i < Count; ++i)
        {
            byte[] x = cells[i];
            if (x == null || x.Length != 1000 || x[0] != (byte)i ||
                x[999] != (byte)(i >> 8) || x[1] != 0 || x[998] != 0)
                throw new Exception("Cell contents changed");
        }
        return "SMALL_PAGE_OK count=524288 bytesEach=1000 aliases=verified zeroFill=verified";
    }
}
