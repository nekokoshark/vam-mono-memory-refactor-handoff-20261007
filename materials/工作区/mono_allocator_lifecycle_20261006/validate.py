"""One reproducible entry for original-runtime, policy and failure tests."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def main(mode: str) -> None:
    assert mode in ("BASELINE", "MODIFIED", "ROLLBACK")
    records = []
    for script, arguments in (("test_suite.py", [mode]), ("lifecycle.py", [mode]),
                               ("lifecycle.py", [mode, "failure"]), ("sections.py", [mode])):
        argv = [sys.executable, str(HERE/script), *arguments]
        run = subprocess.run(argv, cwd=HERE, capture_output=True, text=True, timeout=180)
        records.append(dict(argv=argv, input=arguments, stdout=run.stdout,
                            stderr=run.stderr, exitStatus=run.returncode))
        (HERE/(mode+"_COMBINED.json")).write_text(json.dumps(records, indent=2)+"\n", encoding="utf-8")
        if run.returncode:
            raise RuntimeError(run.stdout + run.stderr)
    repeats = 1 if mode == "ROLLBACK" else 2
    print(f"VALIDATION_PASS mode={mode} runtime=3x{repeats} lifecycle=1 OOM=1 sections=1")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception as error:
        print("VALIDATION_FAIL " + str(error), flush=True)
        raise SystemExit(70)
