"""Restore a separate copy; never overwrite the game or candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    original = (HERE / "BASELINE.dll").read_bytes()
    modified = (HERE / "MODIFIED_FILE.dll").read_bytes()
    assert hashlib.sha256(original).hexdigest() == patch["baselineSHA256"]
    assert hashlib.sha256(modified).hexdigest() == patch["modifiedSHA256"]
    directory = HERE / "rollback_copy"
    assert not directory.is_symlink()
    directory.mkdir(exist_ok=True)
    target = directory / "mono.dll"
    assert not target.is_symlink() and target.resolve().parent == directory.resolve()
    target.write_bytes(modified)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == patch["modifiedSHA256"]
    target.write_bytes(original)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == patch["baselineSHA256"]
    assert hashlib.sha256((HERE / "MODIFIED_FILE.dll").read_bytes()).hexdigest() == patch["modifiedSHA256"]
    print("ROLLBACK_HASH_PASS baseline=restored candidate=retained gameModified=False")


if __name__ == "__main__":
    main()
