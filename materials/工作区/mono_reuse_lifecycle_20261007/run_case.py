"""Use prior real-runtime assertions; bind their arms to installed A1/new DLLs."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

from prepare import once

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / "mono_interior_commit_lifecycle_20261007"
LEGACY = HERE.parent / "mono_allocator_lifecycle_20261006"
sys.path.insert(0, str(LEGACY))
sys.path.insert(0, str(PRIOR))


def load(path: Path, source: str | None = None) -> types.ModuleType:
    if source is None:
        spec = importlib.util.spec_from_file_location("existing_suite", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        module = types.ModuleType("existing_suite")
        module.__file__ = str(path)
        exec(compile(source, str(path), "exec"), module.__dict__)
    module.HERE = HERE
    if hasattr(module, "PREVIOUS"):
        module.PREVIOUS = PRIOR
    return module


def main(mode: str, kind: str) -> None:
    if mode not in ("BASELINE", "MODIFIED", "ROLLBACK"):
        raise ValueError("Unknown arm")
    if kind in ("idle", "quick", "stress", "sections"):
        suite = load(HERE.parent / "mono_warm_pages_20261006/run_case.py")
        sys.argv = [str(HERE / "run_case.py"), mode, kind]
        suite.main()
    elif kind in ("lifecycle", "failure"):
        load(PRIOR / "lifecycle_test.py").main(mode, failure=kind == "failure")
    elif kind == "warm":
        load(HERE.parent / "mono_warm_pages_20261006/warm_pages.py").main(mode)
    elif kind == "cohort":
        load(PRIOR / "cohort_test.py").main(mode)
    elif kind == "spans":
        load(PRIOR / "span_test.py").main(mode)
    elif kind == "isolation":
        path = PRIOR / "isolation_test.py"
        source = once(path.read_text(encoding="utf-8"),
            "mono_free_span_lifecycle_20261006/PATCH.json", "mono_interior_commit_lifecycle_20261007/PATCH.json")
        load(path, source).main(mode)
    elif kind == "interior":
        path = PRIOR / "interior_test.py"
        source = path.read_text(encoding="utf-8")
        # The old baseline was B7 (no interior policy). A1 already has that
        # policy: enforce the same original expected prefix/deltas for ALL arms.
        source = once(source, 'runtime = patch if mode == "MODIFIED" else old',
            'runtime = patch if mode == "MODIFIED" else old\n    interior_enabled = bool(runtime.get("interiorPolicy"))')
        source = once(source, 'if mode == "MODIFIED" else None', 'if interior_enabled else None')
        source = once(source, '(mode != "MODIFIED" or fallback)', '(not interior_enabled or fallback)')
        source = once(source, '(mode == "MODIFIED" and cold and not fallback)', '(interior_enabled and cold and not fallback)')
        source = once(source, '        if mode == "MODIFIED":\n            delta', '        if interior_enabled:\n            delta')
        load(path, source).main(mode)
    elif kind == "ABI":
        path = PRIOR / "abi_test.py"
        source = once(path.read_text(encoding="utf-8"),
            "mono_free_span_lifecycle_20261006/PATCH.json", "mono_interior_commit_lifecycle_20261007/PATCH.json")
        # Both A1 and this candidate contain the interior-split thunk.
        source = once(source, 'if mode == "MODIFIED": thunks.append(("split_cold_extent", 72, 41))',
            'if "split_cold_extent" in runtime["stubs"]: thunks.append(("split_cold_extent", 72, 41))')
        source = once(source, '    for name, frame, epilogue in thunks:',
            '    if mode == "MODIFIED": thunks.append(("reuse_small", 56, 28))\n    for name, frame, epilogue in thunks:')
        load(path, source).main(mode)
    elif kind == "reuse":
        load(HERE / "test_reuse.py").main(mode)
    else:
        raise ValueError("Unknown case")


if __name__ == "__main__":
    try:
        main(*sys.argv[1:3])
    except Exception:
        import traceback
        traceback.print_exc()
        raise SystemExit(70)
