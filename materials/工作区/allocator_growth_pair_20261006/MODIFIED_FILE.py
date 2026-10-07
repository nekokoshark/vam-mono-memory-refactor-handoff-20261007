"""Fast Mono OS-page/heap frames; no game calls, writes, GC or payload reads."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
WORK = HERE.parent


def mono_regions(query, pointers: list[int], seconds: float = 3,
                 cap: int = 200000) -> tuple[dict, dict]:
    """Query only allocations positively owned by the original GC OS table."""
    if not pointers or len(set(pointers)) != len(pointers):
        raise ValueError("Missing/duplicate GC allocation roots")
    deadline = time.monotonic() + seconds
    observed, allocations = {}, []
    previous_end = 0
    for root in sorted(pointers):
        if root <= 0 or root % 4096 or root < previous_end:
            raise ValueError("Invalid/overlapping GC allocation roots")
        cursor, committed, reserved = root, 0, 0
        while True:
            if len(observed) >= cap or time.monotonic() >= deadline:
                raise ValueError("GC region read bound")
            row = query(cursor)
            start, base, size, state, kind = row
            if start > cursor or size <= 0 or start + size <= cursor:
                raise ValueError("Invalid/nonprogressing VM region")
            if base != root:
                if cursor == root:
                    raise ValueError("GC allocation root no longer mapped")
                break
            if start != cursor or size % 4096 or kind != 0x20000 or state not in (0x1000, 0x2000):
                raise ValueError("GC VM type/layout changed")
            observed[cursor] = row
            if state == 0x1000:
                committed += size
            else:
                reserved += size
            cursor = start + size
        previous_end = cursor
        allocations.append(dict(base=hex(root), committedBytes=committed, reservedBytes=reserved))
    return dict(gcOSRoots=len(pointers), monoCommittedBytes=sum(r["committedBytes"] for r in allocations),
                monoReservedBytes=sum(r["reservedBytes"] for r in allocations),
                regionCount=len(observed), allocations=allocations), observed


def compare(before: dict, after: dict) -> dict:
    if ((before["pid"], before["creationFiletime"]) != (after["pid"], after["creationFiletime"]) or
            before["status"] != "accepted" or after["status"] != "accepted" or
            before["role"] != "start-first-ready" or after["role"] != "return-first-ready"):
        raise ValueError("Pair needs accepted same-process start/return first-ready points")
    result = {"processDelta": {k: after["process"][k] - before["process"][k]
                               for k in ("privateBytes", "workingSetBytes")},
              "monoOSCommittedDeltaBytes": after["totals"]["monoCommittedBytes"] - before["totals"]["monoCommittedBytes"],
              "gcEpochs": [before["counters"]["gc_count"], after["counters"]["gc_count"]],
              "notAnObjectRootProof": True, "notResidentComposition": True}
    a, b = before.get("model"), after.get("model")
    if a is not None and b is not None:
        result["counterModelDelta"] = {k: b[k] - a[k] for k in
            ("allocatedEstimateBytes", "committedLargeFreeBytes", "committedHeapEstimateBytes")}
    else:
        result["counterModelDelta"] = None
    result["privateMinusMonoOSDeltaBytes"] = result["processDelta"]["privateBytes"] - result["monoOSCommittedDeltaBytes"]
    return result


def capture(pid: int, filename: str, role: str) -> int:
    destination = HERE / filename
    if destination.parent.resolve() != HERE or destination.exists():
        raise ValueError("Output must be a new task-local file")
    spec = importlib.util.spec_from_file_location("existing_vm_reader", WORK / "scene_vm_owners_20261003/capture_vm.py")
    vm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vm)
    p = vm.composition.Process(pid)
    result = dict(pid=pid, creationFiletime=p.created, role=role, status="rejected", totals=None,
                  gameCalls=0, gameWrites=0, forcedGC=False, payloadBytesRead=0)
    start = time.monotonic()
    try:
        binding = vm.anchors(p)
        result["utc"] = datetime.now(timezone.utc).isoformat()
        counters, metrics, counters_end, model = None, None, None, None
        metrics, counters, counters_end, estimate = vm.composition.counter_frame(p)
        if counters == counters_end:
            model = estimate
        roots, raw, flag = vm.gc_os_roots(p)
        totals, observed = mono_regions(p.region, roots)
        end_roots, end_raw, end_flag = vm.gc_os_roots(p)
        if roots != end_roots or raw != end_raw or flag != end_flag:
            raise ValueError("GC OS table changed")
        for address, region in observed.items():
            if p.region(address) != region:
                raise ValueError("GC VM region endpoints changed")
        final_roots, final_raw, final_flag = vm.gc_os_roots(p)
        if roots != final_roots or raw != final_raw or flag != final_flag:
            raise ValueError("GC OS table changed during region endpoint verification")
        end_counters, end_metrics = p.counters(), p.read_metrics()
        if counters["gc_count"] != end_counters["gc_count"]:
            raise ValueError("GC epoch changed during allocation capture")
        result.update(status="accepted", totals=totals, binding=binding,
            monoBase=hex(p.base), counters=counters, countersAfter=end_counters,
            process=dict(privateBytes=metrics[0], workingSetBytes=metrics[1]),
            processAfter=dict(privateBytes=end_metrics[0], workingSetBytes=end_metrics[1]),
            model=model, counterFrameStable=counters == counters_end,
            gcOSAndVMEndpointsEqual=True, gcUnchanged=True,
            meaning="Exact positive GC OS allocation ownership for committed VM capacity. Process working set is resident memory; commitment is not residency. Heap-free is a runtime allocation estimate, not live-object bytes. The private-minus-Mono delta is an unresolved remainder plus asynchronous metric boundaries, not a Unity/driver attribution. No object liveness or release authority follows from these counters.")
    except (AssertionError, ValueError, OSError, RuntimeError) as error:
        result["reason"] = type(error).__name__ + ": " + str(error)[:400]
    finally:
        p.close()
    result["captureSeconds"] = time.monotonic() - start
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {k: result.get(k) for k in ("role", "status", "process", "model", "captureSeconds", "reason")}
    summary["totals"] = {k: v for k, v in result["totals"].items() if k != "allocations"} if result["totals"] else None
    print("ALLOCATOR_FRAME " + json.dumps(summary, ensure_ascii=False))
    return 0 if result["status"] == "accepted" else 70


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int)
    parser.add_argument("filename")
    parser.add_argument("--role", choices=("tool-check-only", "start-first-ready", "return-first-ready"), required=True)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(capture(args.pid, args.filename, args.role))
