"""Preserve D4685C71 and replace only reclaim-queue classification."""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / "mono_reuse_lifecycle_20261007"
STATE_WORDS = 1123
NEW_NAMES = ("exactSortRuns", "exactSortPages", "exactSortHeadChanges")
NEW_NATIVE = ("exact_sort_runs", "exact_sort_pages", "exact_sort_head_changes")


def once(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, old[:100]
    return source.replace(old, new, 1)


def main() -> None:
    prior = json.loads((PRIOR / "PATCH.json").read_text(encoding="utf-8"))
    baseline = HERE / "BASELINE.dll"
    if not baseline.exists():
        shutil.copy2(PRIOR / "MODIFIED_FILE.dll", baseline)
    assert hashlib.sha256(baseline.read_bytes()).hexdigest() == prior["modifiedSHA256"]
    (HERE / "BASELINE_PATCH.json").write_text(json.dumps(prior, indent=2) + "\n", encoding="utf-8")
    original = (PRIOR / "reclaim_controller.c").read_text(encoding="utf-8")
    source = once(original, "    u64 warm_hints[32];", """    u64 warm_hints[32];
    u64 exact_sort_runs;
    u64 exact_sort_pages;
    u64 exact_sort_head_changes;
    /* Only GC-locked sorting uses this fixed workspace. Hidden addresses are
     * cleared before a chain commits; the workspace owns no heap objects. */
    u64 exact_heads[513];
    u64 exact_tails[513];""")
    source = once(source, "    state->sort_runs++;", "    state->sort_runs++;\n    state->exact_sort_runs++;")
    source = once(source, "u64 joined = 0, minimum = 8, maximum = 0;\n            volatile u64 heads[8];\n            volatile u64 tails[8];",
        "u64 joined = 0, minimum = 513, maximum = 0;\n            volatile u64* heads = state->exact_heads;\n            volatile u64* tails = state->exact_tails;")
    source = once(source, "density = marks * 8 / (512 / size);\n                if (density > 7) density = 7;", "density = marks;")
    source = once(source, "for (band = 0; band < 8; ++band) { heads[band] = 0; tails[band] = 0; }",
        "for (band = 0; band <= 512; ++band) { heads[band] = 0; tails[band] = 0; }")
    source = once(source, "band = (int)(marked(h) * 8 / (512 / size));\n                if (band > 7) band = 7;", "band = (int)marked(h);")
    source = once(source, "if (tails[band]) find(tails[band])->next = block;\n                else heads[band] = block;\n                tails[band] = block;",
        "if (tails[band]) find(~tails[band])->next = block;\n                else heads[band] = ~block;\n                tails[band] = ~block;")
    source = once(source, "for (band = 0; band < 8; ++band) {\n                if (heads[band]) { find(tails[band])->next = joined; joined = heads[band]; }\n            }",
        "for (band = 0; band <= 512; ++band) {\n                if (heads[band]) { find(~tails[band])->next = joined; joined = ~heads[band]; }\n                heads[band] = tails[band] = 0;\n            }\n            state->exact_sort_pages += count;\n            state->exact_sort_head_changes += joined != old;")
    source = source.replace("Uniform-density chains", "Uniform exact-mark-count chains")
    (HERE / "reclaim_controller.c").write_text(source, encoding="utf-8")
    (HERE / "DIFF_FILE.patch").write_text("".join(difflib.unified_diff(original.splitlines(True),
        source.splitlines(True), fromfile="D4685C71/reclaim_controller.c", tofile="exact/reclaim_controller.c")), encoding="utf-8")
    shutil.copy2(PRIOR / "READONLY_6052.json", HERE / "LIVE_COUNTERS.json")
    print("PREPARE_PASS baseline=D4685C71 original94Words=preserved exactBins=513 workspace=nonowning gameModified=False")


if __name__ == "__main__":
    main()
