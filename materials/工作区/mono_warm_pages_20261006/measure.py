"""Alternate three real-runtime arms; timings are helper-only, never game claims."""
from __future__ import annotations

import json
from pathlib import Path
import statistics
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def main() -> None:
    records, measurements = [], []
    for repeat in range(3):
        for mode in ("BASELINE", "MODIFIED") if repeat % 2 == 0 else ("MODIFIED", "BASELINE"):
            argv = [sys.executable, str(HERE / "warm_pages.py"), mode]
            run = subprocess.run(argv, cwd=HERE, capture_output=True, text=True, timeout=150)
            records.append(dict(argv=argv, input=dict(mode=mode, repeat=repeat + 1),
                                stdout=run.stdout, stderr=run.stderr, exitStatus=run.returncode))
            (HERE / "PERF_COMMANDS.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
            print(run.stdout.rstrip(), flush=True)
            assert run.returncode == 0, run.stderr
            measurements.append(json.loads((HERE / (mode + "_WARM.json")).read_text(encoding="utf-8")))
    summary = {}
    for mode in ("BASELINE", "MODIFIED"):
        rows = [row for row in measurements if row["mode"] == mode]
        summary[mode] = dict(coldRemaps=[r["coldAcquireRemaps"] for r in rows],
            allocationMs=[r["allocationMs"] for r in rows],
            medianAllocationMs=statistics.median(r["allocationMs"] for r in rows),
            allocatedCommittedBytes=[r["rows"][3]["vm"]["monoCommittedBytes"] for r in rows],
            releasedCommittedBytes=[r["rows"][-1]["vm"]["monoCommittedBytes"] for r in rows])
    assert min(summary["BASELINE"]["coldRemaps"]) > 8 * max(summary["MODIFIED"]["coldRemaps"])
    result = dict(summary=summary, measurements=measurements, measuredVaMStutterMs=None,
                  measuredVaMSavingsBytes=None, deployed=False)
    (HERE / "PERFORMANCE.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("PERFORMANCE_PASS repeats=3 order=alternating smallRemapsReduction=over8x gameBenefit=unmeasured")


if __name__ == "__main__":
    main()
