"""Reuse the audited PE graft, adding one small-page callsite and x64 thunk."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from prepare import once

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / "mono_interior_commit_lifecycle_20261007"
CANONICAL = HERE.parent / "mono_allocator_lifecycle_20261006"
NEW_FIELDS = ("warmLookupCalls", "warmLookupHits", "warmLookupStale", "warmLookupMisses",
              "warmLookupNativeFallbacks", "warmSeedScans")


def main() -> None:
    old = json.loads((HERE / "BASELINE_PATCH.json").read_text(encoding="utf-8"))
    assert hashlib.sha256((HERE / "BASELINE.dll").read_bytes()).hexdigest() == old["modifiedSHA256"]
    source = (PRIOR / "build_native.py").read_text(encoding="utf-8")
    source = once(source, '"grow_on_demand", "split_cold_extent"}', '"grow_on_demand", "split_cold_extent", "reuse_small"}')
    source = once(source, '"split_cold_extent": stub_rva + 160}', '"split_cold_extent": stub_rva + 160, "reuse_small": stub_rva + 208}')
    source = once(source, "stub_rva + 208 < data_rva", "stub_rva + 256 < data_rva")
    source = once(source, "stub_offset + 208 - len(text)", "stub_offset + 256 - len(text)")
    source = once(source, "callsites=6 importsAdded=0", "callsites=7 importsAdded=0")
    source = once(source, '(("remember_remap", 36), ("take_prefix", 38))', '(("remember_remap", 36), ("take_prefix", 38), ("reuse_small", 33))')
    insertion = '''    reuse = stubs["reuse_small"]
    # RCX/RDX/R8 preserve the original size/kind/flags. R9 supplies base;
    # the fifth argument is state. Native caller/nonvolatiles stay unchanged.
    stub = (bytes.fromhex("4883ec384c8d0d") + rel(reuse+11, 0) +
            bytes.fromhex("488d05") + rel(reuse+18, state_rva) +
            bytes.fromhex("4889442420e8") + rel(reuse+28, exports["reuse_small"]+delta) +
            bytes.fromhex("4883c438c3"))
    assert len(stub) == 33
    text[reuse-new_rva:reuse-new_rva+len(stub)] = stub
'''
    source = once(source, "    assert len(text) <= data_rva - new_rva", insertion + "    assert len(text) <= data_rva - new_rva")
    source = once(source, '(0x160219, 0x15FF50, "split_cold_extent")]', '(0x160219, 0x15FF50, "split_cold_extent"),\n             (0x161EBA, 0x16060C, "reuse_small")]')
    namespace = {"__name__": "reused_native_builder", "__file__": str(PRIOR / "build_native.py")}
    exec(compile(source, str(PRIOR / "build_native.py"), "exec"), namespace)
    with tempfile.TemporaryDirectory(prefix="build-", dir=HERE) as directory:
        stage = Path(directory)
        for name in ("BASELINE.dll", "AUDIT.json", "RetireSample.cs", "LifecycleSample.cs"):
            shutil.copy2(CANONICAL / name, stage / name)
        shutil.copy2(HERE / "reclaim_controller.c", stage / "reclaim_controller.c")
        namespace["main"](stage, state_words=94, controller_section_alignment=8192)
        patch = json.loads((stage / "PATCH.json").read_text(encoding="utf-8"))
        patch.update(canonicalBaselineSHA256=patch["baselineSHA256"],
            baselineSHA256=old["modifiedSHA256"], baselineStateRVA=old["stateRVA"],
            extraStateFields=old["extraStateFields"] + list(NEW_FIELDS) +
                [f"warmHint{i}Hidden" for i in range(1, 33)],
            nativeStateFields=old["nativeStateFields"] +
                ["warm_lookup_calls", "warm_lookup_hits", "warm_lookup_stale", "warm_lookup_misses",
                 "warm_lookup_native_fallbacks", "warm_seed_scans"] +
                [f"warm_hints[{i}]" for i in range(32)],
            placementPolicy="original small-page nth selection tries non-owning warm hints before original complete search",
            seedScanLimit=8192, hintSlots=32, hintRepresentation="bitwise complement; non-owning",
            growthPolicy=old["growthPolicy"], sortPolicy=old["sortPolicy"], mergePolicy=old["mergePolicy"],
            interiorPolicy=old["interiorPolicy"], warmQuantumBytes=65536,
            deployed=False, deploymentRecord=None)
        for name in ("MODIFIED_FILE.dll", "BUILD.json"):
            shutil.copy2(stage / name, HERE / name)
    (HERE / "PATCH.json").write_text(json.dumps(patch, indent=2) + "\n", encoding="utf-8")
    print("REUSE_BUILD_PASS stateWords=94 callsites=7 newSmallPageSite=0x161eba gameModified=False")


if __name__ == "__main__":
    main()
