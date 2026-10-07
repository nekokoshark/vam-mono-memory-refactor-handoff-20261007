"""Reuse existing original-Mono suites without changing their assertions."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def main() -> None:
    kind = sys.argv[2]
    name = "warm_pages.py" if kind == "warm" else "run_case.py"
    source = HERE.parent / "mono_warm_pages_20261006" / name
    spec = importlib.util.spec_from_file_location("reused_runtime_suite", source)
    suite = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(suite)
    suite.HERE = HERE
    if kind == "warm":
        suite.main(sys.argv[1])
    else:
        suite.main()


if __name__ == "__main__":
    main()
