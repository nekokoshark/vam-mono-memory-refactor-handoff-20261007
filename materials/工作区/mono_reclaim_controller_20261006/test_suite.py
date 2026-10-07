"""Run original runtime vs candidate, retaining commands and literal results."""
from __future__ import annotations

import json
from pathlib import Path
import statistics
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def main(mode: str) -> None:
    runs, cases = [], []
    repeats = 1 if mode == "ROLLBACK" else 2
    for repeat in range(1, repeats + 1):
        for scenario in ("idle", "quick", "stress"):
            output = HERE / f"{mode}_{scenario}_{repeat}.json"
            argv = [sys.executable, str(HERE / "sample.py"), mode, scenario, str(output)]
            result = subprocess.run(argv, cwd=HERE, capture_output=True, text=True, timeout=150)
            runs.append(dict(argv=argv, input=dict(mode=mode, scenario=scenario, repeat=repeat),
                             stdout=result.stdout, stderr=result.stderr, exitStatus=result.returncode))
            (HERE / (mode + "_RUN.json")).write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8")
            assert result.returncode == 0, result.stdout + result.stderr
            case = json.loads(output.read_text(encoding="utf-8"))
            assert case["gameCalls"] == case["gameWrites"] == 0
            if scenario == "idle":
                before = next(row for row in case["rows"] if row["stage"] == "Drop")
                gc_rows = [row for row in case["rows"] if row["stage"].startswith("GC")]
                first = next((n for n, row in enumerate(gc_rows, 1)
                              if row["counters"]["unmapped"] - before["counters"]["unmapped"] > 256 * 1024**2), None)
                assert first == (1 if mode == "MODIFIED" else 3), (mode, first)
                case["firstLargeReturn"] = first
                returned = gc_rows[first - 1]
                preceding = gc_rows[first - 2] if first > 1 else before
                private_drop = preceding["process"]["privateUsageBytes"] - returned["process"]["privateUsageBytes"]
                unmap_delta = returned["counters"]["unmapped"] - preceding["counters"]["unmapped"]
                # Process PrivateUsage includes unrelated Python/loader allocation.
                # Use positively owned Windows GC extents for exact accounting.
                os_drop = preceding["vm"]["monoCommittedBytes"] - returned["vm"]["monoCommittedBytes"]
                assert unmap_delta > 256 * 1024**2 and os_drop == unmap_delta, (os_drop, unmap_delta)
                assert private_drop > 256 * 1024**2
                if mode == "MODIFIED":
                    assert returned["controller"]["lastReturned"] == os_drop
                case["largeReturn"] = dict(privateDropBytes=private_drop, unmapIncreaseBytes=unmap_delta,
                    monoOSCommitDropBytes=os_drop,
                    workingSetDropBytes=preceding["process"]["workingSetBytes"]-returned["process"]["workingSetBytes"])
            if scenario == "stress":
                assert next(r for r in case["rows"] if r["stage"] == "Concurrent")["output"] == \
                    "CONCURRENT_OK workers=4 rounds=32 pinnedLive=verified"
                assert next(r for r in case["rows"] if r["stage"] == "Mixed")["output"] == \
                    "MIXED_OK rounds=8 arrays=strings+references+bytes+indices aliases=preserved"
                assert next(r for r in case["rows"] if r["stage"] == "Exceptions")["output"] == \
                    "EXCEPTIONS_OK dispose=25000 exceptions=250 pinnedLive=verified"
                assert next(r for r in case["rows"] if r["stage"] == "Fragmented")["output"] == \
                    "FRAGMENTED_OK rounds=4 liveSmall=8192 liveLarge=4096 pinnedLive=verified"
            cases.append(case)
    quick = [r["elapsedMs"] for c in cases if c["scenario"] == "quick"
             for r in c["rows"] if ".Reuse" in r["stage"]]
    summary = dict(mode=mode, cases=cases, repeats=repeats, quickReuseMedianMs=statistics.median(quick),
                   measuredVaMSavingsBytes=None)
    (HERE / (mode + "_RESULT.json")).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    first = 1 if mode == "MODIFIED" else 3
    print(f"RUNTIME_PASS mode={mode} scenarios=3 repeats={repeats} firstLargeReturn={first} livePinnedAliasReuse=verified concurrent=4x32 mixed=8 fragmented=4 dispose=25000 gameCalls=0 gameWrites=0")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception as error:
        print("RUNTIME_FAIL " + type(error).__name__ + ": " + str(error))
        raise SystemExit(70)
