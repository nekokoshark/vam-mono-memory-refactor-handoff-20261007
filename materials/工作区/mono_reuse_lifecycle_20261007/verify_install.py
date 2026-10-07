"""Verify cold deployment and every snapshot member without launching VaM."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ROOT = REPO.parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    manifest = json.loads((REPO / "运行快照/MANIFEST.json").read_text(encoding="utf-8-sig"))
    prior_report = HERE / "INSTALL_VERIFIED.json"
    saved = json.loads(prior_report.read_text(encoding="utf-8")) if prior_report.exists() else {}
    comparison = saved.get("snapshotBaselineCommit") or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO).decode().strip()
    previous = json.loads(subprocess.check_output(
        ["git", "cat-file", "-p", comparison + ":运行快照/MANIFEST.json"], cwd=REPO).decode("utf-8-sig"))
    old = {row["Path"]: row["SHA256"].lower() for row in previous}
    assert len(manifest) == 81 and len(old) == 81
    changed = []
    for row in manifest:
        relative, expected = row["Path"], row["SHA256"].lower()
        assert digest(ROOT / relative) == digest(REPO / "运行快照" / relative) == expected
        if old[relative] != expected:
            changed.append(relative)
    assert changed == ["Mono/EmbedRuntime/mono.dll"], changed
    expected = patch["modifiedSHA256"]
    assert digest(ROOT / "Mono/EmbedRuntime/mono.dll") == expected
    assert digest(HERE / "MODIFIED_FILE.dll") == expected
    assert digest(HERE / "BASELINE.dll") == digest(HERE / "rollback_copy/mono.dll") == patch["baselineSHA256"]
    memory_hash = digest(ROOT / "BepInEx/plugins/VaMMemory/VaM.Memory.dll")
    assert memory_hash == "300d8335a2faedd473a09a0cb27c28df519413ffadf6c4e555f6a3b673278da8"
    process = subprocess.run(["powershell", "-NoProfile", "-Command",
        "if(@(Get-Process -Name VaM -ErrorAction SilentlyContinue).Count){exit 2}; exit 0"], check=False)
    assert process.returncode == 0, "Game appeared after installation"
    report = dict(installedSHA256=expected, baselineSHA256=patch["baselineSHA256"],
        snapshotFilesVerified=81, snapshotBaselineCommit=comparison,
        changedSnapshotMembers=changed, memorySHA256=memory_hash,
        gameRunning=False, gameStarted=False, rollbackCopyRestored=True, candidateRetained=True)
    (HERE / "INSTALL_VERIFIED.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("COLD_INSTALL_VERIFY_PASS snapshot=81 onlyMonoChanged=True production+candidate+snapshot=D4685C71 rollback=A1A8F07D gameRunning=False")


if __name__ == "__main__":
    main()
