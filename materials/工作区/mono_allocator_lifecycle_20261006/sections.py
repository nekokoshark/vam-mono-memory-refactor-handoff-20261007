"""Real Mono fragmented growth regression, stopped before the fatal section cap."""
from __future__ import annotations

import ctypes as C
import hashlib
import json
from pathlib import Path
import sys
import time

from sample import FIELDS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COUNT_RVA = 0x269BC8
TABLE_RVA = 0x281AC8
LIMIT = 4096
STOP = LIMIT - 192


def run(mode: str) -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    incident = json.loads((HERE / "REGRESSION.json").read_text(encoding="utf-8"))
    name = {"BASELINE": "BASELINE.dll", "MODIFIED": "MODIFIED_FILE.dll",
            "ROLLBACK": "rollback_copy/mono.dll", "REJECTED": "REJECTED.dll"}[mode]
    path = HERE / name
    expected = (incident["rejectedSHA256"] if mode == "REJECTED" else
                patch["modifiedSHA256" if mode == "MODIFIED" else "baselineSHA256"])
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert sha == expected
    mono = C.CDLL(str(path))
    ptr = C.c_void_p

    def api(name: str, result, *arguments):
        f = getattr(mono, name)
        f.restype, f.argtypes = result, list(arguments)
        return f

    managed = ROOT / "VaM_Data/Managed"
    api("mono_set_assemblies_path", None, C.c_char_p)((str(HERE)+";"+str(managed)).encode("utf-8"))
    api("mono_set_dirs", None, C.c_char_p, C.c_char_p)(str(managed).encode("utf-8"),
                                                                 str(ROOT / "Mono/etc").encode("utf-8"))
    domain = api("mono_jit_init_version", ptr, C.c_char_p, C.c_char_p)(b"SectionRegression", b"v2.0.50727")
    assembly = api("mono_domain_assembly_open", ptr, ptr, C.c_char_p)(domain,
                                               str(HERE / "LifecycleSample.dll").encode("utf-8"))
    assert domain and assembly
    image = api("mono_assembly_get_image", ptr, ptr)(assembly)
    klass = api("mono_class_from_name", ptr, ptr, C.c_char_p, C.c_char_p)(image, b"", b"LifecycleSample")
    method = api("mono_class_get_method_from_name", ptr, ptr, C.c_char_p, C.c_int)
    invoke = api("mono_runtime_invoke", ptr, ptr, ptr, ptr, C.POINTER(ptr))
    collect = api("mono_gc_collect", None, C.c_int)
    generation = api("mono_gc_max_generation", C.c_int)()
    rows = []

    def snapshot(stage: str, output: str) -> None:
        count = C.c_uint64.from_address(mono._handle + COUNT_RVA).value
        assert 0 < count < LIMIT
        table = list((C.c_uint64 * (count * 2)).from_address(mono._handle + TABLE_RVA))
        assert count == C.c_uint64.from_address(mono._handle + COUNT_RVA).value
        spans = sorted(zip(table[::2], table[1::2]))
        assert all(start % 4096 == size % 4096 == 0 and size for start, size in spans)
        assert all(a + n <= b for (a, n), (b, _) in zip(spans, spans[1:]))
        heap = C.c_uint64.from_address(mono._handle + 0x27C7E0).value
        assert sum(table[1::2]) == heap
        state = None
        if mode in ("MODIFIED", "REJECTED"):
            rva = patch["stateRVA"] if mode == "MODIFIED" else 3125760
            state = dict(zip(FIELDS, (C.c_uint64 * len(FIELDS)).from_address(mono._handle + rva)))
            assert state["magic"] == 0x31524C5443524347
            assert state["rejected"] == state["pendingBlock"] == 0
            if mode == "MODIFIED":
                assert state["growthOriginalBlocks"] == state["growthActualBlocks"]
        rows.append(dict(stage=stage, output=output, sections=count, heapBytes=heap,
                         wholeFreeBytes=C.c_uint64.from_address(mono._handle + 0x27C808).value,
                         controller=state))

    def action(name: str) -> None:
        f = method(klass, name.encode(), 0)
        assert f
        exception = ptr()
        value = invoke(f, None, None, C.byref(exception))
        assert not exception.value and value, name
        length = C.c_int.from_address(value + 16).value
        assert 0 <= length < 1024
        output = C.string_at(value + 20, length * 2).decode("utf-16-le")
        snapshot(name, output)

    start = time.perf_counter()
    action("PrepareSectionFragments")
    action("DropSectionFragments")
    collect(generation)
    snapshot("FragmentedGC", "ORIGINAL_MONO_GC_COMPLETED")
    assert rows[-1]["wholeFreeBytes"] > 2 * 1024**2
    blocked = False
    # Each batch has at most 128 payload allocations, safely below the 192-entry
    # headroom. Stop the isolated process, not the game, before the native abort.
    for batch in range(391):
        if rows[-1]["sections"] >= STOP:
            blocked = True
            break
        action("AddSectionBatch")
        if rows[-1]["output"] == "SECTION_ADDED count=50000":
            break
    action("CheckSections")
    count = int(rows[-1]["output"].split("=")[-1])
    if mode == "REJECTED":
        assert blocked and count < 50000, (blocked, count, rows[-1])
        state = rows[-1]["controller"]
        assert state["growthActualBlocks"] < state["growthOriginalBlocks"]
    else:
        assert not blocked and count == 50000
        assert rows[-1]["sections"] < LIMIT // 4
    result = dict(mode=mode, runtimeSHA256=sha, input="8192x8KiB, drop alternate, GC, retain 50000x16KiB",
                  limit=LIMIT, stopBeforeFatal=STOP, blocked=blocked, retained=count,
                  elapsedMs=(time.perf_counter() - start) * 1000, rows=rows,
                  gameCalls=0, gameWrites=0, liveGameCounterCaptured=False)
    (HERE / (mode + "_SECTIONS.json")).write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    if mode == "REJECTED":
        print(f"REGRESSION_REPRODUCED mode=REJECTED retained={count} sections={rows[-1]['sections']} limit=4096 stoppedBeforeFatal=True data=verified")
    else:
        print(f"SECTIONS_PASS mode={mode} retained=50000 limit=4096 data=verified growth=original")


if __name__ == "__main__":
    try:
        run(sys.argv[1])
    except Exception as error:
        print("SECTIONS_FAIL " + type(error).__name__ + ": " + str(error), flush=True)
        raise SystemExit(70)
