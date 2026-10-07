# -*- coding: utf-8 -*-
import io, struct, sys
sys.stdout.reconfigure(encoding="utf-8")

def load(path):
    b = io.open(path, "rb").read()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    coff = pe + 4
    nsec, = struct.unpack_from("<H", b, coff+2)
    optsz, = struct.unpack_from("<H", b, coff+16)
    opt = coff + 20
    magic, = struct.unpack_from("<H", b, opt)
    ddoff = opt + (112 if magic == 0x20b else 96)
    edir_rva, edir_sz = struct.unpack_from("<II", b, ddoff)
    secs = []
    so = opt + optsz
    for i in range(nsec):
        o = so + 40*i
        nm = b[o:o+8].rstrip(b"\0").decode("ascii", "replace")
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", b, o+8)
        secs.append((nm, vaddr, vsize, raddr, rsize))
    def r2o(rva):
        for nm, vaddr, vsize, raddr, rsize in secs:
            if vaddr <= rva < vaddr + max(vsize, rsize):
                return raddr + (rva - vaddr)
        return None
    eo = r2o(edir_rva)
    base       = struct.unpack_from("<I", b, eo+16)[0]
    nfunc      = struct.unpack_from("<I", b, eo+20)[0]
    nnam       = struct.unpack_from("<I", b, eo+24)[0]
    addr_func  = struct.unpack_from("<I", b, eo+28)[0]
    addr_names = struct.unpack_from("<I", b, eo+32)[0]
    names = []
    for i in range(nnam):
        nrva, = struct.unpack_from("<I", b, r2o(addr_names) + 4*i)
        o = r2o(nrva); e = b.index(b"\0", o)
        names.append(b[o:e].decode("ascii", "replace"))
    return b, secs, r2o, base, nfunc, nnam, addr_func, names

path = r"F:\vam1.22.0.12\Mono\EmbedRuntime\mono.dll"
b, secs, r2o, base, nfunc, nnam, addr_func, names = load(path)
print("== mono.dll : %d named exports, base=%d, nfunc=%d ==" % (nnam, base, nfunc))
g = sorted(set(s for s in names if s.startswith("mono_gc")))
print("\n-- mono_gc_* exports (%d) --" % len(g))
for s in g: print("   " + s)
print("\n-- heap walk / dump / stat / profiler related (any prefix) --")
key = ("walk","dump","heap","snapshot","iterate","foreach","class_get","prof")
for s in sorted(set(x for x in names if any(k in x.lower() for k in key))):
    print("   " + s)
