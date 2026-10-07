"""Same PE/native preservation checks, with exact 94-word prefix mapping."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import types

from prepare import once

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / "mono_reuse_lifecycle_20261007"


def main() -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    old = json.loads((HERE / "BASELINE_PATCH.json").read_text(encoding="utf-8"))
    declaration = (HERE / "reclaim_controller.c").read_text(encoding="utf-8").split(
        "typedef struct ReclaimState {",1)[1].split("} ReclaimState;",1)[0]
    names = []
    for name, count in re.findall(r"u64 (\w+)(?:\[(\d+)\])?;",declaration):
        names.extend([f"{name}[{i}]" for i in range(int(count))] if count else [name])
    assert names[:94] == old["nativeStateFields"] and names == patch["nativeStateFields"]
    assert len(names) == 1123 and names[97] == "exact_heads[0]" and names[610] == "exact_tails[0]"
    source = (PRIOR / "verify.py").read_text(encoding="utf-8")
    start = source.index('    declaration =')
    end = source.index('    a, b =',start)
    source = source[:start]+source[end:]
    source = once(source, '== {0x161EBA}', '== set()')
    source = once(source, 'patch["stateBytes"] == 94 * 8', 'patch["stateBytes"] == 1123 * 8')
    source = once(source,'struct.pack("<94Q", 0x31524C5443524347, 256 * 1024**2, *([0] * 92))',
        'struct.pack("<1123Q", 0x31524C5443524347, 256 * 1024**2, *([0] * 1121))')
    source = once(source, 'originalFieldPrefixWords=56', 'originalFieldPrefixWords=94')
    source = once(source, 'stateWords=94, gameModified=False', 'stateWords=1123, gameModified=False')
    source = once(source, 'STRUCTURE_PASS A1=bound callsites=7 new=0x161eba originalNth+growth=unchanged WX=none stateWords=94',
        'EXACT_STRUCTURE_PASS baseline=D4685C71 hooks=7 newHooks=0 originals=unchanged WX=none stateWords=1123')
    module = types.ModuleType("audited_pe_checks")
    module.__file__ = str(PRIOR / "verify.py")
    exec(compile(source,module.__file__,"exec"),module.__dict__)
    module.HERE = HERE
    module.main()


if __name__ == "__main__":
    main()
