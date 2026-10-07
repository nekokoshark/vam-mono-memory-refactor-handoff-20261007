"""Restore/retest an independent copy; candidate and game remain unchanged."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def main() -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    target = HERE / "rollback_copy/mono.dll"
    target.parent.mkdir(exist_ok=True)
    assert target.resolve().parent == (HERE / "rollback_copy").resolve()
    baseline, candidate = HERE / "BASELINE.dll", HERE / "MODIFIED_FILE.dll"
    assert hashlib.sha256(baseline.read_bytes()).hexdigest() == patch["baselineSHA256"]
    assert hashlib.sha256(candidate.read_bytes()).hexdigest() == patch["modifiedSHA256"]
    shutil.copy2(candidate, target)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == patch["modifiedSHA256"]
    shutil.copy2(baseline, target)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == patch["baselineSHA256"]
    print("ROLLBACK_HASH_PASS baseline=A1A8F07D-restored candidate=retained gameModified=False", flush=True)
    result = subprocess.run([sys.executable, str(HERE / "validate.py"), "ROLLBACK"], cwd=HERE)
    assert hashlib.sha256(candidate.read_bytes()).hexdigest() == patch["modifiedSHA256"]
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
