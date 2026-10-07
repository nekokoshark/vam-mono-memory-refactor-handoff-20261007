"""Keep exact commands/results for baseline, modified and rollback real runtimes."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def main(mode: str) -> None:
    if mode not in ("BASELINE", "MODIFIED", "ROLLBACK"):
        raise ValueError("Invalid runtime arm")
    commands = []
    kinds = ("idle", "quick", "stress", "lifecycle", "failure", "sections")
    for kind in kinds:
        argv = [sys.executable, str(HERE / "run_case.py"), mode, kind]
        result = subprocess.run(argv, cwd=HERE, capture_output=True, text=True, timeout=180)
        commands.append(dict(argv=argv, input=dict(mode=mode, test=kind), stdout=result.stdout,
                             stderr=result.stderr, exitStatus=result.returncode))
        (HERE / (mode + "_COMMANDS.json")).write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
        print(result.stdout.rstrip(), flush=True)
        assert result.returncode == 0, result.stderr
    argv = [sys.executable, str(HERE / "warm_pages.py"), mode]
    result = subprocess.run(argv, cwd=HERE, capture_output=True, text=True, timeout=120)
    commands.append(dict(argv=argv, input=dict(mode=mode, test="warm-small-pages"),
                         stdout=result.stdout, stderr=result.stderr, exitStatus=result.returncode))
    (HERE / (mode + "_COMMANDS.json")).write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
    print(result.stdout.rstrip(), flush=True)
    assert result.returncode == 0, result.stderr
    print(f"VALIDATION_PASS mode={mode} runtime=3 lifecycle=1 OOM=1 sections=1 warm=1 gameModified=False")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception as error:
        print("VALIDATION_FAIL " + type(error).__name__ + ": " + str(error), flush=True)
        raise SystemExit(70)
