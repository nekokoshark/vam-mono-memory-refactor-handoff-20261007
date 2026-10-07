"""Reuse the PE/ABI builder; preserve all seven previously installed hooks."""
from __future__ import annotations

import json
from pathlib import Path
import types

from prepare import NEW_NAMES, NEW_NATIVE, STATE_WORDS, once

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / "mono_reuse_lifecycle_20261007"


def main() -> None:
    source = (PRIOR / "build.py").read_text(encoding="utf-8")
    source = once(source, "state_words=94", f"state_words={STATE_WORDS}")
    source = once(source, 'REUSE_BUILD_PASS stateWords=94 callsites=7 newSmallPageSite=0x161eba gameModified=False',
        'REUSE_STAGE_PASS stateWords=1123 callsites=7 hooks=preserved gameModified=False')
    source = once(source, "extraStateFields=old[\"extraStateFields\"] + list(NEW_FIELDS) +\n                [f\"warmHint{i}Hidden\" for i in range(1, 33)],",
        "extraStateFields=old[\"extraStateFields\"] + list(EXACT_NAMES) +\n                [f\"exactHead{i}Hidden\" for i in range(513)] + [f\"exactTail{i}Hidden\" for i in range(513)],")
    start = source.index('            nativeStateFields=old["nativeStateFields"] +')
    end = source.index('            placementPolicy=', start)
    source = source[:start] + '''            nativeStateFields=old["nativeStateFields"] + list(EXACT_NATIVE) +
                [f"exact_heads[{i}]" for i in range(513)] + [f"exact_tails[{i}]" for i in range(513)],
''' + source[end:]
    module = types.ModuleType("audited_builder")
    module.__file__ = str(PRIOR / "build.py")
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    module.HERE = HERE
    module.EXACT_NAMES, module.EXACT_NATIVE = NEW_NAMES, NEW_NATIVE
    module.main()
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    patch.update(sortPolicy="stable exact mark-count descending within each validated (kind,size) chain",
        sortingBins=513, fixedWorkspaceBytes=8208, scratchWordOffset=97, noNewHooks=True)
    (HERE / "PATCH.json").write_text(json.dumps(patch, indent=2) + "\n", encoding="utf-8")
    print("EXACT_BUILD_PASS stateWords=1123 hooks=7 newHooks=0 marking+locks+growth=preserved gameModified=False")


if __name__ == "__main__":
    main()
