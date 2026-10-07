"""Independent real-Mono policy tests: native chains, prefix VM and demand growth."""
from __future__ import annotations

import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import time

from sample import FIELDS
from test_vm import capture as capture_vm

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main(mode: str, failure: bool = False) -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    path = HERE / {"BASELINE": "BASELINE.dll", "MODIFIED": "MODIFIED_FILE.dll",
                   "ROLLBACK": "rollback_copy/mono.dll"}[mode]
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert sha == patch["modifiedSHA256" if mode == "MODIFIED" else "baselineSHA256"]
    mono = C.CDLL(str(path))
    ptr = C.c_void_p

    def api(name: str, result, *args):
        f = getattr(mono, name)
        f.restype, f.argtypes = result, list(args)
        return f

    assemblies = str(HERE) + ";" + str(ROOT / "VaM_Data/Managed")
    api("mono_set_assemblies_path", None, C.c_char_p)(assemblies.encode())
    api("mono_set_dirs", None, C.c_char_p, C.c_char_p)(
        str(ROOT / "VaM_Data/Managed").encode(), str(ROOT / "Mono/etc").encode())
    domain = api("mono_jit_init_version", ptr, C.c_char_p, C.c_char_p)(b"AllocatorLifecycle", b"v2.0.50727")
    assembly = api("mono_domain_assembly_open", ptr, ptr, C.c_char_p)(
        domain, str(HERE / "LifecycleSample.dll").encode())
    assert domain and assembly
    img = api("mono_assembly_get_image", ptr, ptr)(assembly)
    klass = api("mono_class_from_name", ptr, ptr, C.c_char_p, C.c_char_p)(img, b"", b"LifecycleSample")
    method = api("mono_class_get_method_from_name", ptr, ptr, C.c_char_p, C.c_int)
    invoke = api("mono_runtime_invoke", ptr, ptr, ptr, ptr, C.POINTER(ptr))
    collect = api("mono_gc_collect", None, C.c_int)
    generation = api("mono_gc_max_generation", C.c_int)()
    core = runpy.run_path(str(HERE.parent / "mono_unmap_20260930/MODIFIED_FILE.py"))
    reader = core["WindowsReader"](os.getpid())
    find = C.CFUNCTYPE(ptr, C.c_uint64)(mono._handle + 0x15EE50)
    rows = []

    def integer(address: int, width: int = 8) -> int:
        return int.from_bytes(C.string_at(address, width), "little")

    def controller() -> dict | None:
        if mode != "MODIFIED": return None
        values = (C.c_uint64 * len(FIELDS)).from_address(mono._handle + patch["stateRVA"])
        result = dict(zip(FIELDS, values))
        assert result["rejected"] == 0 and result["pendingBlock"] == 0, result
        assert result["freeAfter"] <= result["reserveBytes"], result
        return result

    def pending_order() -> dict:
        kinds = integer(mono._handle + 0x265998, 4)
        assert 1 <= kinds <= 16
        total = inversions = lists = 0
        for kind in range(kinds):
            if kind & ~1 == 2: continue
            pending = integer(mono._handle + 0x2659A0 + kind * 32 + 8)
            if not pending: continue
            for size in range(1, 257):
                block, previous, seen = integer(pending + size * 8), 8, set()
                if block: lists += 1
                while block:
                    assert block not in seen and total < 1048576
                    seen.add(block); total += 1
                    h = find(block)
                    assert integer(h) == size and integer(h+40, 1) == kind
                    marks = [integer(h+48+8*i) for i in range(8)]
                    count = sum(x.bit_count() for x in marks)
                    assert count <= 512 // size
                    band = min(7, count * 8 // (512 // size))
                    inversions += band > previous
                    previous, block = band, integer(h+8)
        return dict(pages=total, lists=lists, inversions=inversions)

    def inventory() -> dict:
        marker = integer(mono._handle + 0x269F70)
        extents = []
        for bucket in range(61):
            block = integer(mono._handle + 0x269D70 + bucket*8)
            seen = set()
            while block:
                assert block not in seen and len(extents) < 1048576
                seen.add(block)
                h = find(block)
                assert integer(h+32) == marker
                size, flags = integer(h), integer(h+41, 1)
                assert block % 4096 == size % 4096 == 0 and size > 0
                extents.append(dict(start=block, end=block+size, unmapped=bool(flags & 2)))
                block = integer(h+8)
        extents.sort(key=lambda r: r["start"])
        assert all(a["end"] <= b["start"] for a, b in zip(extents, extents[1:]))
        counters = core["read_counters"](reader, mono._handle)
        assert sum(r["end"]-r["start"] for r in extents) == counters["free"]
        assert sum(r["end"]-r["start"] for r in extents if r["unmapped"]) == counters["unmapped"]
        return dict(blocks=len(extents), freeBytes=counters["free"], unmappedBytes=counters["unmapped"])

    def snapshot(stage: str, output: str, elapsed: float) -> None:
        counters = core["read_counters"](reader, mono._handle)
        rows.append(dict(stage=stage, output=output, elapsedMs=elapsed, controller=controller(),
                         counters=counters, vm=capture_vm(mono._handle), inventory=inventory()))
        assert counters == core["read_counters"](reader, mono._handle)

    def action(name: str) -> None:
        f = method(klass, name.encode(), 0)
        assert f
        error = ptr()
        start = time.perf_counter()
        value = invoke(f, None, None, C.byref(error))
        assert not error.value and value, "Managed helper exception: " + name
        length = integer(value+16, 4)
        assert length < 1024
        output = C.string_at(value+20, length*2).decode("utf-16-le")
        snapshot(name, output, (time.perf_counter()-start)*1000)

    def gc(stage: str) -> None:
        start = time.perf_counter()
        collect(generation)
        snapshot(stage, "ORIGINAL_MONO_GC_COMPLETED", (time.perf_counter()-start)*1000)

    try:
        if failure:
            # Local native routines acquire the original allocator lock and
            # increment/decrement GC_dont_gc. This fork has no Mono exports.
            disabled = C.CFUNCTYPE(None)(mono._handle+0x158EB8)
            enabled = C.CFUNCTYPE(None)(mono._handle+0x158E8C)
            admission = integer(mono._handle+0x269BFC, 4)
            maximum = C.c_uint64.from_address(mono._handle+0x27C7E8)
            saved = maximum.value
            disabled()
            try:
                maximum.value = integer(mono._handle+0x27C7E0) + 8*1024**2
                action("AllocationFailure")
                assert rows[-1]["output"] == "OOM_OK originalException=caught"
            finally:
                maximum.value = saved
                enabled()
            assert admission == integer(mono._handle+0x269BFC, 4)
            action("AfterFailure"); gc("AfterFailureGC")
            (HERE / (mode+"_FAILURE.json")).write_text(json.dumps(dict(mode=mode, rows=rows,
                  gameCalls=0, gameWrites=0), indent=2)+"\n", encoding="utf-8")
            print(f"FAILURE_PASS mode={mode} originalOOM=caught limit=restored recovery=verified gameCalls=0 gameWrites=0")
            return
        action("PrepareCells"); action("DropCells"); gc("SparseGC")
        order = pending_order()
        if mode == "MODIFIED":
            assert order["inversions"] == 0 and order["pages"] > 1000, order
            assert rows[-1]["controller"]["sortChangedLists"] > 0
        action("CheckCells"); action("RefillCells"); gc("RefillGC"); action("CheckCells")
        action("DropCellRoots"); gc("CellsReleasedGC")
        action("PrepareLarge"); action("DropLarge")
        for cycle in range(1, 4): gc("LargeFreeGC" + str(cycle))
        before = rows[-1]
        action("ReplaceLarge")
        after = rows[-1]
        (HERE/(mode+"_LIFECYCLE_TRACE.json")).write_text(json.dumps(rows,indent=2)+"\n",encoding="utf-8")
        if mode == "MODIFIED":
            avoided = after["controller"]["remapAvoidedBytes"] - before["controller"]["remapAvoidedBytes"]
            assert avoided > 64*1024**2, avoided
            assert after["controller"]["splitPrefixes"] > before["controller"]["splitPrefixes"]
            assert after["counters"]["heap"] == before["counters"]["heap"]
            native_delta = before["counters"]["unmapped"] - after["counters"]["unmapped"]
            vm_delta = after["vm"]["monoCommittedBytes"] - before["vm"]["monoCommittedBytes"]
            assert vm_delta == native_delta, (vm_delta, native_delta)
            assert 300*1024**2 <= vm_delta < 320*1024**2, vm_delta
        gc("PinnedPrefixGC"); action("CheckLarge")
        action("DropReplacement"); gc("PrefixReleasedGC")
        final = rows[-1]["controller"]
        if mode == "MODIFIED":
            assert final["sortRuns"] > 0 and final["mergedBlocks"] > 0
            assert final["growthCalls"] > 0 and final["growthActualBlocks"] == final["growthOriginalBlocks"]
        result = dict(mode=mode, runtimeSHA256=sha, rows=rows, pendingOrder=order,
                      gameCalls=0, gameWrites=0, measuredVaMSavingsBytes=None)
        (HERE / (mode+"_LIFECYCLE.json")).write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
        print(f"LIFECYCLE_PASS mode={mode} cells=1048576 refill=262144 prefix=300MiB inventory=closed pinned=verified gameCalls=0 gameWrites=0")
    finally:
        reader.close()


if __name__ == "__main__":
    try:
        main(sys.argv[1], "failure" in sys.argv[2:])
    except Exception as error:
        print("LIFECYCLE_FAIL " + type(error).__name__ + ": " + str(error), flush=True)
        raise SystemExit(70)
