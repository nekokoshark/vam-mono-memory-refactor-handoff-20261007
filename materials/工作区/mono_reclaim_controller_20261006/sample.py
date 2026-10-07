"""Exercise real embedded Mono only in this independent process."""
from __future__ import annotations

import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import time
from test_vm import capture as vm_capture

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools/pydeps"))
FIELDS = ("magic", "reserveBytes", "collections", "scannedBlocks", "freeBefore",
          "freeAfter", "decommittedBytes", "decommittedBlocks", "rejected", "lastGC",
          "lastReturned", "lastScanned")


def run(mode: str, scenario: str, output_path: Path) -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    path = HERE / {"BASELINE": "BASELINE.dll", "MODIFIED": "MODIFIED_FILE.dll",
                   "ROLLBACK": "rollback_copy/mono.dll"}[mode]
    expected = patch["modifiedSHA256" if mode == "MODIFIED" else "baselineSHA256"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    os.environ["MONO_PATH"] = str(HERE) + ";" + str(ROOT / "VaM_Data/Managed")
    mono = C.CDLL(str(path))
    ptr, integer, cstr = C.c_void_p, C.c_int, C.c_char_p

    def api(name: str, result, *arguments):
        function = getattr(mono, name)
        function.restype, function.argtypes = result, list(arguments)
        return function

    api("mono_set_assemblies_path", None, cstr)(os.environ["MONO_PATH"].encode("utf-8"))
    api("mono_set_dirs", None, cstr, cstr)(str(ROOT / "VaM_Data/Managed").encode("utf-8"),
                                        str(ROOT / "Mono/etc").encode("utf-8"))
    domain = api("mono_jit_init_version", ptr, cstr, cstr)(b"ReclaimControllerTest", b"v2.0.50727")
    assembly = api("mono_domain_assembly_open", ptr, ptr, cstr)(domain, str(HERE / "RetireSample.dll").encode("utf-8"))
    assert domain and assembly
    image = api("mono_assembly_get_image", ptr, ptr)(assembly)
    klass = api("mono_class_from_name", ptr, ptr, cstr, cstr)(image, b"", b"RetireSample")
    invoke = api("mono_runtime_invoke", ptr, ptr, ptr, ptr, C.POINTER(ptr))
    methods = {name: api("mono_class_get_method_from_name", ptr, ptr, cstr, integer)(klass, name.encode(), 0)
               for name in ("Prepare", "Drop", "CheckLive", "Reuse", "Concurrent", "Mixed", "Exceptions", "Fragmented")}
    assert all(methods.values())
    core = runpy.run_path(str(HERE.parent / "mono_unmap_20260930/MODIFIED_FILE.py"))
    reader = core["WindowsReader"](os.getpid())
    rows: list[dict] = []

    def state() -> dict | None:
        if mode != "MODIFIED":
            return None
        values = (C.c_uint64 * len(FIELDS)).from_address(mono._handle + patch["stateRVA"])
        result = dict(zip(FIELDS, values))
        assert result["magic"] == 0x31524C5443524347 and result["reserveBytes"] == 256 * 1024**2
        assert result["rejected"] == 0 and result["freeAfter"] <= result["reserveBytes"], result
        return result

    if mode == "MODIFIED":
        lookup = C.WinDLL("ntdll").RtlLookupFunctionEntry
        lookup.argtypes, lookup.restype = (C.c_uint64, C.POINTER(C.c_uint64), ptr), ptr
        image_base = C.c_uint64()
        unwind = lookup(mono._handle + patch["controllerRVA"] + 20, C.byref(image_base), None)
        assert unwind and image_base.value == mono._handle, "Loader did not register native unwind data"

    def action(name: str, stage: str | None = None) -> None:
        error = ptr()
        started = time.perf_counter()
        value = invoke(methods[name], None, None, C.byref(error))
        elapsed = (time.perf_counter() - started) * 1000
        assert not error.value and value, "Real Mono managed method exception: " + name
        length = int.from_bytes(C.string_at(value + 16, 4), "little", signed=True)
        assert 0 <= length < 1024
        output = C.string_at(value + 20, length * 2).decode("utf-16-le")
        rows.append(dict(stage=stage or name, output=output, elapsedMs=elapsed,
                         counters=core["read_counters"](reader, mono._handle),
                         process=reader.process_counters(), controller=state(), vm=vm_capture(mono._handle)))

    collect = api("mono_gc_collect", None, integer)
    generation = api("mono_gc_max_generation", integer)()

    def gc(stage: str) -> None:
        started = time.perf_counter()
        collect(generation)
        elapsed = (time.perf_counter() - started) * 1000
        action("CheckLive", stage)
        assert rows[-1]["output"] == "CHECK_LIVE_OK retiredContainerAlive=False"
        rows[-1]["elapsedMs"] = elapsed

    try:
        action("Prepare")
        action("Drop")
        if scenario == "idle":
            for cycle in range(1, 10):
                gc("GC" + str(cycle))
            action("Reuse", "ReuseAfterIdle")
        elif scenario == "quick":
            for cycle in range(1, 5):
                for number in range(1, 4):
                    gc(f"Quick{cycle}.GC{number}")
                action("Reuse", f"Quick{cycle}.Reuse")
                action("Drop", f"Quick{cycle}.Drop")
        else:
            action("Concurrent")
            gc("Concurrent.GC")
            action("Mixed")
            action("Fragmented")
            action("Exceptions")
            gc("Final.GC")
            action("Reuse", "ReuseAfterStress")
        assert all(row["output"] == "REUSE_OK liveAndNewPages=verified"
                   for row in rows if "Reuse" in row["stage"])
        result = dict(mode=mode, scenario=scenario, pid=os.getpid(), loadedMono=str(path),
                      loadedSHA256=expected, rows=rows, liveBytes=33554432,
                      temporaryBytes=536870912, testProcessOnly=True, gameCalls=0, gameWrites=0)
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"ISOLATED_PASS mode={mode} scenario={scenario} livePinnedAliasReuse=verified gameCalls=0 gameWrites=0")
    finally:
        reader.close()


if __name__ == "__main__":
    try:
        run(sys.argv[1], sys.argv[2], Path(sys.argv[3]))
    except Exception as error:
        print("ISOLATED_FAIL " + type(error).__name__ + ": " + str(error), flush=True)
        raise SystemExit(70)
