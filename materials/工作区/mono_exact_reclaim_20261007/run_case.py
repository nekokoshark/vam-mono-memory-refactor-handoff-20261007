"""Keep preceding original-method assertions, binding baseline metadata to D4."""
from __future__ import annotations

from pathlib import Path
import sys
import types

from prepare import once

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / "mono_reuse_lifecycle_20261007"


def main(mode: str, kind: str) -> None:
    if kind == "exact":
        from test_exact import main as run
        run(mode)
        return
    if kind == "reuse":
        source = (PRIOR / "test_reuse.py").read_text(encoding="utf-8")
        source = once(source, '    filename = {"BASELINE":',
            '    reuse_enabled = runtime.get("hintSlots") == 32\n    filename = {"BASELINE":')
        assert source.count('mode == "MODIFIED" and label') == 3
        source = source.replace('mode == "MODIFIED" and label', 'reuse_enabled and label')
        module = types.ModuleType("original_reuse_fixture")
        module.__file__ = str(PRIOR / "test_reuse.py")
        exec(compile(source, module.__file__, "exec"), module.__dict__)
        module.HERE = HERE
        module.main(mode)
        return
    source = (PRIOR / "run_case.py").read_text(encoding="utf-8")
    source = source.replace('"mono_interior_commit_lifecycle_20261007/PATCH.json"',
        '"mono_reuse_lifecycle_20261007/PATCH.json"')
    source = once(source, "module.PREVIOUS = PRIOR", "module.PREVIOUS = BASE_META")
    source = once(source, '    if mode == "MODIFIED": thunks.append(("reuse_small", 56, 28))',
        '    if "reuse_small" in runtime["stubs"]: thunks.append(("reuse_small", 56, 28))')
    module = types.ModuleType("preceding_original_suites")
    module.__file__ = str(PRIOR / "run_case.py")
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    module.HERE, module.BASE_META = HERE, PRIOR
    module.main(mode, kind)


if __name__ == "__main__":
    main(*sys.argv[1:3])
