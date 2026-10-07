"""Build only the isolated original-Mono workload and fixed native reader."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MSVC = Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64")


def main() -> None:
    baseline = HERE / "BASELINE.dll"
    expected = "1c023c2516d002f5762bb5bd9636cbaa4b46ab421bfa396b874539ed9f668fa1"
    if not baseline.exists():
        shutil.copy2(ROOT / "Mono/EmbedRuntime/mono.dll", baseline)
    assert hashlib.sha256(baseline.read_bytes()).hexdigest() == expected
    old = json.loads((HERE.parent / "mono_warm_pages_20261006/PATCH.json").read_text(encoding="utf-8"))
    if not (HERE / "PATCH.json").exists():
        (HERE / "PATCH.json").write_text(json.dumps(dict(baselineSHA256=expected,
            baselineStateRVA=old["stateRVA"]), indent=2) + "\n", encoding="utf-8")
    records = []
    commands = [
        [str(MSVC / "cl.exe"), "/nologo", "/c", "/O2", "/GS-", "/Zl", "/W4", "/WX", "/Brepro", "/Fopending_probe.obj", "pending_probe.c"],
        [str(MSVC / "link.exe"), "/nologo", "/dll", "/noentry", "/nodefaultlib", "/machine:x64", "/dynamicbase", "/nxcompat", "/Brepro", "/out:pending_probe.dll", "pending_probe.obj"],
        [r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe", "/nologo", "/noconfig", "/nostdlib+", "/optimize+", "/target:library", "/out:PendingCohort.dll",
         "/reference:" + str(ROOT / "VaM_Data/Managed/mscorlib.dll"), "PendingCohort.cs", str(HERE.parent / "mono_allocator_lifecycle_20261006/LifecycleSample.cs")],
    ]
    for argv in commands:
        result = subprocess.run(argv, cwd=HERE, capture_output=True, text=True, timeout=120)
        records.append(dict(argv=argv, stdout=result.stdout, stderr=result.stderr, exitStatus=result.returncode))
        (HERE / "PROBE_BUILD.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        assert result.returncode == 0, result.stdout + result.stderr
    print("PROBE_BUILD_PASS originalManagedTypes=True nativeReader=bounded gameCalls=0")


if __name__ == "__main__":
    main()
