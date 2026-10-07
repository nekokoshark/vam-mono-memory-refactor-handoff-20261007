"""Measure real native small-page acquisitions, VM closure and same live objects."""
from __future__ import annotations

import ctypes as C
import hashlib
import json
from pathlib import Path
import runpy
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LEGACY = HERE.parent / "mono_allocator_lifecycle_20261006"
sys.path.insert(0, str(LEGACY))
from sample import FIELDS
from test_vm import capture as capture_vm


def main(mode: str) -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    name = {"BASELINE": "BASELINE.dll", "MODIFIED": "MODIFIED_FILE.dll",
            "ROLLBACK": "rollback_copy/mono.dll"}[mode]
    path = HERE / name
    expected = patch["modifiedSHA256" if mode == "MODIFIED" else "baselineSHA256"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    mono = C.CDLL(str(path))
    ptr, integer, string = C.c_void_p, C.c_int, C.c_char_p

    def api(name, result, *args):
        f = getattr(mono, name)
        f.restype, f.argtypes = result, list(args)
        return f

    managed = ROOT / "VaM_Data/Managed"
    api("mono_set_assemblies_path", None, string)((str(HERE) + ";" + str(managed)).encode("utf-8"))
    api("mono_set_dirs", None, string, string)(str(managed).encode("utf-8"),
                                              str(ROOT / "Mono/etc").encode("utf-8"))
    domain = api("mono_jit_init_version", ptr, string, string)(b"WarmPageTest", b"v2.0.50727")
    assembly = api("mono_domain_assembly_open", ptr, ptr, string)(domain, str(HERE / "WarmPages.dll").encode("utf-8"))
    assert domain and assembly
    image = api("mono_assembly_get_image", ptr, ptr)(assembly)
    klass = api("mono_class_from_name", ptr, ptr, string, string)(image, b"", b"WarmPages")
    method = api("mono_class_get_method_from_name", ptr, ptr, string, integer)
    invoke = api("mono_runtime_invoke", ptr, ptr, ptr, ptr, C.POINTER(ptr))
    collect = api("mono_gc_collect", None, integer)
    disabled = C.CFUNCTYPE(None)(mono._handle + 0x158EB8)
    enabled = C.CFUNCTYPE(None)(mono._handle + 0x158E8C)
    core = runpy.run_path(str(LEGACY.parent / "mono_unmap_20260930/MODIFIED_FILE.py"))
    reader = core["WindowsReader"](__import__("os").getpid())
    state_rva = patch["stateRVA"] if mode == "MODIFIED" else patch["baselineStateRVA"]
    names = FIELDS + (("warmBatches", "warmBytes", "warmExtraBytes") if mode == "MODIFIED" else ())
    rows = []

    def snapshot(stage, output, milliseconds=0):
        state = dict(zip(names, (C.c_uint64 * len(names)).from_address(mono._handle + state_rva)))
        assert state["magic"] == 0x31524C5443524347
        assert state["rejected"] == state["pendingBlock"] == 0
        c = core["read_counters"](reader, mono._handle)
        vm = capture_vm(mono._handle)
        # The GC OS table also owns scratch/header allocations outside the
        # registered object heap. Do not equate its committed total with heap.
        assert vm["monoReservedBytes"] == c["unmapped"], (vm, c)
        rows.append(dict(stage=stage, output=output, elapsedMs=milliseconds, state=state,
                         counters=c, vm=vm,
                         sections=C.c_uint64.from_address(mono._handle + 0x269BC8).value))

    def action(name):
        f = method(klass, name.encode(), 0)
        assert f
        error = ptr()
        start = time.perf_counter()
        value = invoke(f, None, None, C.byref(error))
        ms = (time.perf_counter() - start) * 1000
        assert not error.value and value, name
        length = C.c_int.from_address(value + 16).value
        assert 0 < length < 200
        out = C.string_at(value + 20, length * 2).decode("utf-16-le")
        snapshot(name, out, ms)

    try:
        action("Seed")
        action("Drop")
        for i in range(3):
            collect(0)
        snapshot("ColdReady", "ORIGINAL_MONO_GC_COMPLETED")
        disabled()
        try:
            action("Allocate")
        finally:
            enabled()
        collect(0)
        action("Check")
        action("Drop")
        collect(0)
        snapshot("Released", "ORIGINAL_MONO_GC_COMPLETED")
        cold, allocated = rows[2:4]
        remaps = allocated["state"]["remapCalls"] - cold["state"]["remapCalls"]
        assert remaps > 100, "Test did not exercise the cold prefix path"
        assert allocated["counters"]["gc_count"] == cold["counters"]["gc_count"]
        assert allocated["counters"]["heap"] == cold["counters"]["heap"]
        assert allocated["sections"] == cold["sections"], "Remap must not register new heap sections"
        assert rows[-1]["state"]["freeAfter"] <= 256 * 1024**2
        if mode == "MODIFIED":
            assert allocated["state"]["warmBatches"] > cold["state"]["warmBatches"]
            assert allocated["state"]["warmExtraBytes"] - cold["state"]["warmExtraBytes"] <= remaps * 65536
        result = dict(mode=mode, runtimeSHA256=expected, rows=rows, coldAcquireRemaps=remaps,
                      allocationMs=allocated["elapsedMs"], gameWrites=0, gameCalls=0,
                      forcedGC="isolated helper only", measuredVaMSavingsBytes=None)
        (HERE / (mode + "_WARM.json")).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"WARM_PAGES_PASS mode={mode} cells=524288 coldRemaps={remaps} "
              f"allocationMs={allocated['elapsedMs']:.3f} sections=unchanged VM=closed aliases=verified gameCalls=0")
    finally:
        reader.close()


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception as error:
        traceback.print_exc()
        print("WARM_PAGES_FAIL " + type(error).__name__ + ": " + str(error), flush=True)
        raise SystemExit(70)
