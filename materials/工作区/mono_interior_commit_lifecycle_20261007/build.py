"""Rebuild the prior policies, adding only accepted-interior demand commitment."""
from __future__ import annotations

import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / "mono_free_span_lifecycle_20261006"
LEGACY = HERE.parent / "mono_allocator_lifecycle_20261006"
BASE_SHA = "b7c1f56dd38fb70b6ee7e66f3dd65dd86f7a10e832006a5e5a2c3837928974b2"
NEW_FIELDS = ("interiorSplitCalls", "interiorColdSplits", "interiorFullBytes",
              "interiorDeferredBytes", "interiorFallbacks")


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main() -> None:
    assert hashlib.sha256((HERE / "BASELINE.dll").read_bytes()).hexdigest() == BASE_SHA
    old = json.loads((PREVIOUS / "PATCH.json").read_text(encoding="utf-8"))
    before = (PREVIOUS / "reclaim_controller.c").read_text(encoding="utf-8")
    after = (HERE / "reclaim_controller.c").read_text(encoding="utf-8")

    def fields(source: str) -> list[str]:
        body = source.split("typedef struct ReclaimState {", 1)[1].split("} ReclaimState;", 1)[0]
        return re.findall(r"u64 (\w+);", body)

    assert len(fields(before)) == 51 and fields(after)[:51] == fields(before)
    assert fields(after)[51:] == ["_".join(re.findall(r"[A-Z]?[a-z]+", n)).lower() for n in NEW_FIELDS]
    # Existing policy bodies are byte-identical; only the new adapter is added.
    removed = after.split("/* Only the original allocator's accepted interior split", 1)
    old_tail = "/* Preserve both original expansion batches exactly."
    normalized = removed[0] + old_tail + removed[1].split(old_tail, 1)[1]
    normalized = normalized.replace("Six original callsites", "Five original callsites")
    normalized = normalized.replace(" * allocator lock. Interior splits first preserve both cold headers, then use\n * this same demand-remap transaction. No unlocked partial state is exposed.",
        " * allocator lock. Interior/blacklisted splits keep the original full remap.\n * No partially mapped header is ever published on a free list.")
    for name in fields(after)[51:]: normalized = normalized.replace(f"    u64 {name};\n", "")
    assert normalized == before
    builder, verifier = module("interior_builder", HERE / "build_native.py"), module("interior_verifier", HERE / "verify_native.py")
    with tempfile.TemporaryDirectory(prefix="build-", dir=HERE) as directory:
        stage = Path(directory)
        for name in ("BASELINE.dll", "AUDIT.json", "RetireSample.cs", "LifecycleSample.cs"):
            shutil.copy2(LEGACY / name, stage / name)
        shutil.copy2(HERE / "reclaim_controller.c", stage / "reclaim_controller.c")
        builder.main(stage, state_words=56, controller_section_alignment=8192)
        verifier.HERE = stage
        verifier.main()
        patch = json.loads((stage / "PATCH.json").read_text(encoding="utf-8"))
        patch["canonicalBaselineSHA256"] = patch["baselineSHA256"]
        patch.update(baselineSHA256=BASE_SHA, baselineStateRVA=old["stateRVA"],
            extraStateFields=tuple(old["extraStateFields"]) + NEW_FIELDS,
            nativeStateFields=fields(after), warmQuantumBytes=65536,
            sortPolicy=old["sortPolicy"], mergePolicy=old["mergePolicy"],
            interiorPolicy="metadata split preserves cold on both sides; common demand commit",
            deploymentRecord=None, deployed=False, replacesRejectedSHA256=None)
        for name in ("MODIFIED_FILE.dll", "BUILD.json", "STRUCTURE.json"):
            shutil.copy2(stage / name, HERE / name)
    (HERE / "PATCH.json").write_text(json.dumps(patch, indent=2) + "\n", encoding="utf-8")
    diff = ""
    for filename, original in (("reclaim_controller.c", before),
                               ("build_native.py", (LEGACY / "build.py").read_text(encoding="utf-8")),
                               ("verify_native.py", (LEGACY / "verify.py").read_text(encoding="utf-8"))):
        modified = (HERE / filename).read_text(encoding="utf-8")
        diff += "".join(difflib.unified_diff(original.splitlines(True), modified.splitlines(True),
            fromfile="prior/"+filename, tofile=HERE.name+"/"+filename))
    (HERE / "DIFF_FILE.patch").write_text(diff, encoding="utf-8")
    print("INTERIOR_BUILD_PASS stateWords=56 oldPolicies=unchanged callsites=6 gameModified=False")


if __name__ == "__main__":
    main()
