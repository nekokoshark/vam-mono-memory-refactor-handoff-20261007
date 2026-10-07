"""Reuse the audited PE graft builder; keep the deployed DLL untouched."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
LEGACY = HERE.parent / "mono_allocator_lifecycle_20261006"
BASE_SHA = "d89ccf26fd75b354244f7225b978667c215d54681a2565df624ac59fb6ac323e"


def module(name: str, filename: Path):
    spec = importlib.util.spec_from_file_location(name, filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main() -> None:
    assert hashlib.sha256((HERE / "BASELINE.dll").read_bytes()).hexdigest() == BASE_SHA
    builder = module("audited_graft", LEGACY / "build.py")
    verifier = module("audited_structure", LEGACY / "verify.py")
    with tempfile.TemporaryDirectory(prefix="build-", dir=HERE) as directory:
        stage = Path(directory)
        assert stage.resolve().parent == HERE.resolve() and stage.name.startswith("build-")
        for name in ("BASELINE.dll", "AUDIT.json", "RetireSample.cs", "LifecycleSample.cs"):
            shutil.copy2(LEGACY / name, stage / name)
        shutil.copy2(HERE / "reclaim_controller.c", stage / "reclaim_controller.c")
        builder.main(stage, state_words=32)
        verifier.HERE = stage
        verifier.main()
        patch = json.loads((stage / "PATCH.json").read_text(encoding="utf-8"))
        patch["canonicalBaselineSHA256"] = patch["baselineSHA256"]
        patch["baselineSHA256"] = BASE_SHA
        old = json.loads((LEGACY / "PATCH.json").read_text(encoding="utf-8"))
        patch["baselineStateRVA"] = old["stateRVA"]
        patch["warmQuantumBytes"] = 65536
        patch["deploymentRecord"] = None
        patch["deployed"] = False
        patch["replacesRejectedSHA256"] = None
        for name in ("MODIFIED_FILE.dll", "BUILD.json", "STRUCTURE.json",
                     "RetireSample.dll", "LifecycleSample.dll"):
            shutil.copy2(stage / name, HERE / name)
    (HERE / "PATCH.json").write_text(json.dumps(patch, indent=2) + "\n", encoding="utf-8")
    compile_command = [r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        "/nologo", "/noconfig", "/nostdlib+", "/optimize+", "/target:library",
        "/out:WarmPages.dll", "/reference:" + str(HERE.parents[1] / "VaM_Data/Managed/mscorlib.dll"),
        "WarmPages.cs"]
    result = subprocess.run(compile_command, cwd=HERE, capture_output=True, text=True, timeout=60)
    records = json.loads((HERE / "BUILD.json").read_text(encoding="utf-8"))
    records.append(dict(argv=compile_command, stdout=result.stdout, stderr=result.stderr,
                        exitStatus=result.returncode))
    (HERE / "BUILD.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    print("WARM_BUILD_PASS quantum=65536 expansion=unchanged deployed=False")


if __name__ == "__main__":
    main()
