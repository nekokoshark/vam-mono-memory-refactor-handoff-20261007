"""Run existing real-Mono regression methods against task-local DLL copies."""
from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
LEGACY = HERE.parent / "mono_allocator_lifecycle_20261006"
sys.path.insert(0, str(LEGACY))
import lifecycle
import sample
import sections


def main() -> None:
    mode, kind = sys.argv[1:3]
    for source in (sample, lifecycle, sections):
        source.HERE = HERE
    if kind in ("idle", "quick", "stress"):
        sample.run(mode, kind, HERE / (mode + "_" + kind + ".json"))
    elif kind == "sections":
        # Existing code reads the incident descriptor but does not load the
        # rejected DLL unless explicitly asked. Keep that descriptor transient.
        descriptor = HERE / "REGRESSION.json"
        descriptor.write_text((LEGACY / "REGRESSION.json").read_text(encoding="utf-8"), encoding="utf-8")
        try:
            sections.run(mode)
        finally:
            descriptor.unlink()
    elif kind in ("lifecycle", "failure"):
        lifecycle.main(mode, failure=kind == "failure")
    else:
        raise ValueError("Unknown real runtime test")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("CASE_FAIL " + type(error).__name__ + ": " + str(error), flush=True)
        raise SystemExit(70)
