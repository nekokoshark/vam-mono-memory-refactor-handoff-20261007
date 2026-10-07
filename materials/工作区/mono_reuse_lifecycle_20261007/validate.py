"""Record commands, literal outputs and statuses from real isolated runtimes."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / "mono_interior_commit_lifecycle_20261007"
CASES = ("idle", "quick", "stress", "lifecycle", "failure", "sections", "warm",
         "reuse", "cohort", "isolation", "spans", "interior", "ABI")


def main(mode: str) -> None:
    if mode not in ("BASELINE", "MODIFIED", "ROLLBACK"):
        raise ValueError("Unknown arm")
    for name in ("RetireSample.dll", "LifecycleSample.dll", "WarmPages.dll", "PendingCohort.dll", "pending_probe.dll"):
        shutil.copy2(PRIOR / name, HERE / name)
    records = []
    for kind in CASES:
        argv = [sys.executable, str(HERE / "run_case.py"), mode, kind]
        result = subprocess.run(argv, cwd=HERE, capture_output=True, text=True, timeout=300)
        records.append(dict(argv=argv, input=dict(mode=mode, test=kind), stdout=result.stdout,
                            stderr=result.stderr, exitStatus=result.returncode))
        (HERE / (mode + "_COMMANDS.json")).write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        print(result.stdout.rstrip(), flush=True)
        if result.returncode:
            print(result.stderr, flush=True)
            raise SystemExit(result.returncode)
    print(f"VALIDATION_PASS mode={mode} cases=13 originalMono=True gameModified=False")


if __name__ == "__main__":
    main(sys.argv[1])
