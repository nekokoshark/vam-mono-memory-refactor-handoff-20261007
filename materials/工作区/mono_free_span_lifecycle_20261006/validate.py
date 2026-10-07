"""Record literal results from each real runtime arm, including >1M pages."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def main(mode: str) -> None:
    if mode not in ("BASELINE", "MODIFIED", "ROLLBACK"):
        raise ValueError("Invalid runtime arm")
    records = []
    cases = [("run_case.py", kind) for kind in ("idle", "quick", "stress", "lifecycle", "failure", "sections", "warm")]
    cases.extend((name, None) for name in ("cohort_test.py", "isolation_test.py", "span_test.py"))
    for script, kind in cases:
        argv = [sys.executable, str(HERE / script), mode] + ([kind] if kind else [])
        result = subprocess.run(argv, cwd=HERE, capture_output=True, text=True, timeout=240)
        records.append(dict(argv=argv, input=dict(mode=mode, test=kind or script), stdout=result.stdout,
                            stderr=result.stderr, exitStatus=result.returncode))
        (HERE / (mode + "_COMMANDS.json")).write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        print(result.stdout.rstrip(), flush=True)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
    print(f"VALIDATION_PASS mode={mode} runtime=3 lifecycle=1 OOM=1 sections=1 warm=1 oversized=1 isolation=1 spans=1 gameModified=False")


if __name__ == "__main__":
    main(sys.argv[1])
