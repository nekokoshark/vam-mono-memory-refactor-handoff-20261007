"""Reuse the audited graft builder; preserve the installed 1C Mono as baseline."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
LEGACY = HERE.parent / "mono_allocator_lifecycle_20261006"
WARM = HERE.parent / "mono_warm_pages_20261006"
BASE_SHA = "1c023c2516d002f5762bb5bd9636cbaa4b46ab421bfa396b874539ed9f668fa1"
EXTRA_FIELDS = ("chainScans", "chainPagesValidated", "chainHeaderRejects", "chainMarkRejects",
                "chainLimitRejects", "lastRejectedKind", "lastRejectedSize", "lastRejectReason",
                "maxChainPages", "lastPendingPages", "uniformChains")


def module(name: str, filename: Path):
    spec = importlib.util.spec_from_file_location(name, filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main() -> None:
    assert hashlib.sha256((HERE / "BASELINE.dll").read_bytes()).hexdigest() == BASE_SHA
    def state_fields(source: Path) -> list[str]:
        text = source.read_text(encoding="utf-8").split("typedef struct ReclaimState {", 1)[1].split("} ReclaimState;", 1)[0]
        return re.findall(r"u64 (\w+);", text)
    original_fields = state_fields(WARM / "reclaim_controller.c")
    candidate_fields = state_fields(HERE / "reclaim_controller.c")
    assert len(original_fields) == 32 and candidate_fields[:32] == original_fields
    assert candidate_fields[32:] == ["_".join(re.findall(r"[A-Z]?[a-z]+", name)).lower() for name in EXTRA_FIELDS]
    builder = module("audited_graft", LEGACY / "build.py")
    verifier = module("audited_structure", LEGACY / "verify.py")
    with tempfile.TemporaryDirectory(prefix="build-", dir=HERE) as directory:
        stage = Path(directory)
        for name in ("BASELINE.dll", "AUDIT.json", "RetireSample.cs", "LifecycleSample.cs"):
            shutil.copy2(LEGACY / name, stage / name)
        shutil.copy2(HERE / "reclaim_controller.c", stage / "reclaim_controller.c")
        builder.main(stage, state_words=32 + len(EXTRA_FIELDS), controller_section_alignment=8192)
        verifier.HERE = stage
        verifier.main()
        patch = json.loads((stage / "PATCH.json").read_text(encoding="utf-8"))
        patch["canonicalBaselineSHA256"] = patch["baselineSHA256"]
        patch["baselineSHA256"] = BASE_SHA
        old = json.loads((WARM / "PATCH.json").read_text(encoding="utf-8"))
        patch.update(baselineStateRVA=old["stateRVA"], extraStateFields=EXTRA_FIELDS,
            nativeStateFields=candidate_fields,
            warmQuantumBytes=65536, sortPolicy="independent kind/size chains; registered-heap page bound; uniform fast path",
            deploymentRecord=None, deployed=False, replacesRejectedSHA256=None)
        for name in ("MODIFIED_FILE.dll", "BUILD.json", "STRUCTURE.json", "RetireSample.dll", "LifecycleSample.dll"):
            shutil.copy2(stage / name, HERE / name)
    shutil.copy2(WARM / "WarmPages.dll", HERE / "WarmPages.dll")
    (HERE / "PATCH.json").write_text(json.dumps(patch, indent=2) + "\n", encoding="utf-8")
    before, after = (WARM / "reclaim_controller.c").read_text(encoding="utf-8"), (HERE / "reclaim_controller.c").read_text(encoding="utf-8")
    import difflib
    diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile="mono_warm_pages_20261006/reclaim_controller.c", tofile="mono_reclaim_cohorts_20261006/reclaim_controller.c"))
    (HERE / "DIFF_FILE.patch").write_text(diff, encoding="utf-8")
    print("COHORT_BUILD_PASS validation=independent heapBound=registered uniform=skip stateWords=43 deployed=False")


if __name__ == "__main__":
    main()
