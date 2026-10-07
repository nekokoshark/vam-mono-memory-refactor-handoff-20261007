"""Real oversized pending-queue regression; run exclusively in a child process."""
from __future__ import annotations

import ctypes as C
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = HERE.parent / "mono_reclaim_cohorts_20261006"
FIRST_FIELDS = ("magic", "reserveBytes", "collections", "scannedBlocks", "freeBefore",
    "freeAfter", "decommittedBytes", "decommittedBlocks", "rejected", "lastGC", "lastReturned",
    "lastScanned", "sortRuns", "sortPages", "sortLists", "sortChangedLists", "mergeCalls",
    "mergedBlocks", "remapCalls", "remapFullBytes", "remapPrefixBytes", "remapAvoidedBytes",
    "splitPrefixes", "growthCalls", "growthOriginalBlocks", "growthActualBlocks",
    "pendingBlock", "pendingFull", "pendingBytes", "warmBatches", "warmBytes", "warmExtraBytes")


class MemoryStatus(C.Structure):
    _fields_ = [("length", C.c_uint32), ("load", C.c_uint32)] + [
        (name, C.c_uint64) for name in ("physical", "available", "pageFile", "availablePageFile",
                                      "virtual", "availableVirtual", "extended")]


class Chain(C.Structure):
    _fields_ = [(n, C.c_uint64) for n in ("kind", "size", "head", "pages", "inversions",
                                       "invalid", "reason", "badBlock")] + [("bands", C.c_uint64 * 8)]


class Report(C.Structure):
    _fields_ = [(n, C.c_uint64) for n in ("kinds", "chains", "pages", "invalid",
                                       "globalLimitExceeded")] + [("chain", Chain * 4096)]


def main(mode: str) -> None:
    if mode not in ("BASELINE", "MODIFIED", "ROLLBACK"):
        raise ValueError("Invalid runtime arm")
    memory = MemoryStatus()
    memory.length = C.sizeof(memory)
    query = C.WinDLL("kernel32").GlobalMemoryStatusEx
    query.argtypes, query.restype = (C.POINTER(MemoryStatus),), C.c_int
    assert query(C.byref(memory))
    assert memory.available >= 14 * 1024**3, "Require 6 GiB workload + 8 GiB physical headroom"
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    name = {"BASELINE": "BASELINE.dll", "MODIFIED": "MODIFIED_FILE.dll", "ROLLBACK": "rollback_copy/mono.dll"}[mode]
    path = HERE / name
    expected = patch["modifiedSHA256" if mode == "MODIFIED" else "baselineSHA256"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    mono = C.CDLL(str(path))
    ptr, integer, string = C.c_void_p, C.c_int, C.c_char_p

    def api(name: str, result, *args):
        f = getattr(mono, name)
        f.restype, f.argtypes = result, list(args)
        return f

    api("mono_set_assemblies_path", None, string)((str(HERE) + ";" + str(ROOT / "VaM_Data/Managed")).encode())
    api("mono_set_dirs", None, string, string)(str(ROOT / "VaM_Data/Managed").encode(), str(ROOT / "Mono/etc").encode())
    domain = api("mono_jit_init_version", ptr, string, string)(b"PendingCohortTest", b"v2.0.50727")
    assembly = api("mono_domain_assembly_open", ptr, ptr, string)(domain, str(HERE / "PendingCohort.dll").encode())
    assert domain and assembly
    image = api("mono_assembly_get_image", ptr, ptr)(assembly)
    classes = {n: api("mono_class_from_name", ptr, ptr, string, string)(image, b"", n.encode())
               for n in ("PendingCohort", "LifecycleSample")}
    get_method = api("mono_class_get_method_from_name", ptr, ptr, string, integer)
    invoke = api("mono_runtime_invoke", ptr, ptr, ptr, ptr, C.POINTER(ptr))
    collect = api("mono_gc_collect", None, integer)
    disable = C.CFUNCTYPE(None)(mono._handle + 0x158EB8)
    enable = C.CFUNCTYPE(None)(mono._handle + 0x158E8C)
    probe = C.CDLL(str(HERE / "pending_probe.dll")).pending_probe
    probe.argtypes, probe.restype = (ptr, C.POINTER(Report)), None
    rows: list[dict] = []
    state_rva = patch["stateRVA" if mode == "MODIFIED" else "baselineStateRVA"]
    previous_fields = json.loads((PREVIOUS / "PATCH.json").read_text())["extraStateFields"]
    fields = FIRST_FIELDS + tuple(patch.get("extraStateFields", ())) if mode == "MODIFIED" else FIRST_FIELDS + tuple(previous_fields)

    def snapshot(stage: str, output: str, elapsed: float) -> dict:
        report = Report()
        start = time.perf_counter()
        probe(mono._handle, C.byref(report))
        chains = [dict(kind=r.kind, size=r.size, pages=r.pages, inversions=r.inversions,
                       invalid=r.invalid, reason=r.reason, bands=list(r.bands))
                  for r in report.chain[:report.chains]]
        state = dict(zip(fields, (C.c_uint64 * len(fields)).from_address(mono._handle + state_rva)))
        assert state["magic"] == 0x31524C5443524347
        row = dict(stage=stage, output=output, elapsedMs=elapsed, probeMs=(time.perf_counter()-start)*1000,
            pendingPages=report.pages, invalid=report.invalid, chains=chains, state=state,
            heap=C.c_uint64.from_address(mono._handle + 0x27C7E0).value,
            sections=C.c_uint64.from_address(mono._handle + 0x269BC8).value)
        rows.append(row)
        return row

    def action(klass: str, name: str, sample: bool = False) -> str:
        method = get_method(classes[klass], name.encode(), 0)
        assert method
        error = ptr()
        start = time.perf_counter()
        value = invoke(method, None, None, C.byref(error))
        assert value and not error.value, klass + "." + name
        length = C.c_int.from_address(value + 16).value
        assert 0 < length < 256
        out = C.string_at(value + 20, length * 2).decode("utf-16-le")
        if sample:
            snapshot(klass + "." + name, out, (time.perf_counter()-start)*1000)
        return out

    disable()
    try:
        action("PendingCohort", "Prepare")
        action("LifecycleSample", "PrepareCells")
        action("PendingCohort", "Drop")
        action("LifecycleSample", "DropCells")
    finally:
        enable()
    before = snapshot("BeforeGC", "ORIGINAL_MONO_ALLOCATIONS_COMPLETED", 0)
    start = time.perf_counter()
    collect(0)
    sparse = snapshot("SparseGC", "ORIGINAL_MONO_GC_COMPLETED", (time.perf_counter()-start)*1000)
    assert sparse["invalid"] == 0 and sparse["pendingPages"] > 1048576, sparse
    varied = [r for r in sparse["chains"] if sum(x > 0 for x in r["bands"]) >= 3 and r["pages"] > 1000]
    assert varied, "Missing independent varying-density small-object cohort"
    rejects = sparse["state"]["rejected"] - before["state"]["rejected"]
    # Baseline16AAF already includes cohort admission; every arm must keep it.
    assert all(r["inversions"] == 0 for r in varied), varied
    assert rejects == 0
    assert sparse["state"]["chainLimitRejects"] == 0
    assert sparse["state"]["maxChainPages"] > 1048576
    assert sparse["state"]["uniformChains"] > 0
    assert sparse["state"]["chainHeaderRejects"] == sparse["state"]["chainMarkRejects"] == 0
    assert sparse["state"]["sortPages"] > before["state"]["sortPages"]
    action("PendingCohort", "Check")
    action("LifecycleSample", "CheckCells")
    disable()
    try:
        action("LifecycleSample", "RefillCells", True)
    finally:
        enable()
    action("LifecycleSample", "CheckCells")
    action("PendingCohort", "Check")
    action("PendingCohort", "Release")
    action("LifecycleSample", "DropCellRoots")
    collect(0)
    end = snapshot("Released", "ROOTS_RELEASED_ORIGINAL_GC_COMPLETED", 0)
    assert end["state"]["freeAfter"] <= 256 * 1024**2
    result = dict(mode=mode, runtimeSHA256=expected, memoryAvailableBefore=memory.available,
                  rows=rows, gameCalls=0, gameWrites=0, measuredVaMSavingsBytes=None)
    (HERE / (mode + "_COHORT.json")).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    inversions = sum(r["inversions"] for r in varied)
    print(f"COHORT_PASS mode={mode} pendingPages={sparse['pendingPages']} independentInversions={inversions} "
          f"globalRejects={rejects} rootedAliases=verified gameCalls=0 gameWrites=0")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception as error:
        print("COHORT_FAIL " + type(error).__name__ + ": " + str(error), flush=True)
        raise SystemExit(70)
