"""Bounded native pending-page metadata sample; no pixels, writes or calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import runpy
import struct
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent


def main(pid: int) -> None:
    prior = HERE.parent / "mono_reuse_lifecycle_20261007"
    patch = json.loads((prior / "PATCH.json").read_text(encoding="utf-8"))
    core = runpy.run_path(str(HERE.parent / "mono_unmap_20260930/MODIFIED_FILE.py"))
    reader = core["WindowsReader"](pid)
    start = time.monotonic()
    result = dict(pid=pid, status="rejected", sampledPages=None, gameCalls=0, gameWrites=0,
        coverage="At most 128 leading pending pages per (kind,size); last GC marks, not current live roots.")
    reads = byte_count = 0
    try:
        base, path = reader.module()
        disk = path.read_bytes()
        assert hashlib.sha256(disk).hexdigest() == patch["modifiedSHA256"]
        pe = core["pefile"].PE(data=disk)
        def read(address: int, size: int) -> bytes:
            nonlocal reads, byte_count
            if reads >= 24000 or byte_count + size > 8 * 1024**2 or time.monotonic() - start > 2:
                raise ValueError("metadata sample budget")
            reads += 1
            byte_count += size
            return reader.read(address, size)
        code = patch["sections"][0]
        for rva, count in [(0x15EE50, 80), (code["rva"], code["bytes"])]:
            assert read(base + rva, count) == pe.get_data(rva, count)
        before = core["read_counters"](reader, base)
        top_raw = read(base + 0x2BDCD0, 16384)
        top = struct.unpack("<2048Q", top_raw)
        sentinel = core["read_u64"](reader, base + 0x2BDCC8)
        kinds = struct.unpack("<i", read(base + 0x265998, 4))[0]
        assert 0 < kinds <= 16
        table = read(base + 0x2659A0, 32 * kinds)
        cache = {}
        def header(block: int) -> int:
            key, node = block >> 22, top[(block >> 22) & 2047]
            for _ in range(64):
                if node == sentinel or node <= 4096:
                    raise ValueError("header missing")
                if node not in cache:
                    cache[node] = read(node + 0x2010, 16)
                ident, successor = struct.unpack("<QQ", cache[node])
                if ident == key:
                    return struct.unpack("<Q", read(node + ((block >> 12) & 1023) * 8, 8))[0]
                node = successor
            raise ValueError("header lookup bound")
        rows, guards = [], []
        for kind in range(kinds):
            if (kind & ~1) == 2:
                continue
            pending = struct.unpack_from("<Q", table, 32 * kind + 8)[0]
            if not pending:
                continue
            raw = read(pending, 257 * 8)
            guards.append((kind, pending, raw))
            for size in range(1, 257):
                block = struct.unpack_from("<Q", raw, size * 8)[0]
                counts, bands, seen = [], [], set()
                while block and len(counts) < 128:
                    assert block % 4096 == 0 and block not in seen
                    seen.add(block)
                    h = header(block)
                    assert h > 4096
                    data = read(h, 112)
                    assert struct.unpack_from("<Q", data)[0] == size and data[40] == kind and not data[41] & 2
                    count = sum(n.bit_count() for n in struct.unpack_from("<8Q", data, 48))
                    assert count <= 512 // size
                    counts.append(count)
                    bands.append(min(7, count * 8 // (512 // size)))
                    block = struct.unpack_from("<Q", data, 8)[0]
                if counts:
                    rows.append(dict(kind=kind, words=size, sampleCount=len(counts), truncated=bool(block),
                        exactInversions=sum(a < b for a, b in zip(counts, counts[1:])),
                        sameBandExactInversions=sum(counts[i] < counts[i+1] and bands[i] == bands[i+1] for i in range(len(counts)-1)),
                        markCounts=counts))
        assert read(base + 0x2659A0, len(table)) == table, "kind table endpoint changed"
        assert all(read(node + 0x2010, 8) == raw[:8] for node, raw in cache.items()), "header index identity changed"
        endpoints = {kind: (raw, read(address, len(raw))) for kind, address, raw in guards}
        accepted, rejected = [], []
        for row in rows:
            offset = row["words"] * 8
            raw, end = endpoints[row["kind"]]
            if raw[offset:offset+8] == end[offset:offset+8]:
                accepted.append(row)
            else:
                rejected.append(dict(kind=row["kind"], words=row["words"], reason="head changed; values excluded"))
        after = core["read_counters"](reader, base)
        assert before["gc_count"] == after["gc_count"], "GC endpoint changed"
        assert accepted, "no stable chain samples"
        result.update(status="accepted-partial", sampledPages=sum(r["sampleCount"] for r in accepted), rows=accepted,
            rejectedChains=rejected, sampledSameBandInversions=sum(r["sameBandExactInversions"] for r in accepted),
            counters=before, countersEnd=after, globallyAtomic=False, addressABAExcluded=False)
    except Exception as error:
        result["reason"] = f"{type(error).__name__}: {error}; line={traceback.extract_tb(error.__traceback__)[-1].lineno}"
    finally:
        reader.close()
    result.update(readCalls=reads, readBytes=byte_count, seconds=time.monotonic()-start)
    (HERE / "DENSITY_SAMPLE.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"DENSITY_{result['status'].upper()} sampledPages={result['sampledPages']} sameBandInversions={result.get('sampledSameBandInversions')} reads={reads} writes=0 calls=0")


if __name__ == "__main__":
    main(int(sys.argv[1]))
