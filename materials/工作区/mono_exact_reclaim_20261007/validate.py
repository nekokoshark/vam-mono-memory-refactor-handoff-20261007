"""Fourteen sequential isolated cases; literal evidence retained per arm."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
CASES = "idle quick stress lifecycle failure sections warm reuse cohort isolation spans interior ABI exact".split()


def main(mode: str) -> None:
    assert mode in ("BASELINE", "MODIFIED", "ROLLBACK")
    prior = HERE.parent / "mono_interior_commit_lifecycle_20261007"
    for name in ("RetireSample.dll","LifecycleSample.dll","WarmPages.dll","PendingCohort.dll","pending_probe.dll"):
        shutil.copy2(prior / name, HERE / name)
    records = []
    failures = []
    for case in CASES:
        argv = [sys.executable, str(HERE / "run_case.py"), mode, case]
        run = subprocess.run(argv, cwd=HERE, capture_output=True, text=True, timeout=300)
        records.append(dict(argv=argv,input=dict(mode=mode,test=case),stdout=run.stdout,stderr=run.stderr,exitStatus=run.returncode))
        (HERE / (mode+"_COMMANDS.json")).write_text(json.dumps(records,indent=2)+"\n",encoding="utf-8")
        print(run.stdout.rstrip(),flush=True)
        if run.returncode:
            print(run.stderr,flush=True)
            failures.append(case)
    if failures:
        print(f"VALIDATION_FAIL mode={mode} cases=14 failures={','.join(failures)} originalMono=True gameModified=False")
        raise SystemExit(1)
    print(f"VALIDATION_PASS mode={mode} cases=14 originalMono=True gameModified=False")


if __name__ == "__main__":
    main(sys.argv[1])
