"""Cold-install the verified candidate and record disk/snapshot identity."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    target = ROOT / "Mono/EmbedRuntime/mono.dll"
    assert digest(HERE / "BASELINE.dll") == patch["baselineSHA256"]
    assert digest(HERE / "MODIFIED_FILE.dll") == patch["modifiedSHA256"]
    before = digest(target)
    assert before in (patch["baselineSHA256"], patch["modifiedSHA256"])
    manifest_path = WORK / "\u8fd0\u884c\u5feb\u7167/MANIFEST.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    argv = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(HERE / "install.ps1"), "-Mode", "Install"]
    result = subprocess.run(argv, cwd=HERE, capture_output=True, timeout=180)
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    command = dict(argv=argv, cwd=str(HERE), input=dict(mode="Install", testCopy=False,
        baselineSHA256=before, candidateSHA256=patch["modifiedSHA256"]),
        stdout=stdout, stderr=stderr, exitStatus=result.returncode)
    (HERE / "DEPLOY_COMMAND.json").write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")
    print(stdout.rstrip(), flush=True)
    assert result.returncode == 0, stderr
    installed = digest(target)
    assert installed == patch["modifiedSHA256"]
    current = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    for row in current:
        snapshot = WORK / "\u8fd0\u884c\u5feb\u7167" / row["Path"]
        assert digest(snapshot).upper() == row["SHA256"].upper()
        assert digest(ROOT / row["Path"]).upper() == row["SHA256"].upper()
    old = {row["Path"]: row["SHA256"] for row in previous}
    changed = [row["Path"] for row in current if old.get(row["Path"]) != row["SHA256"]]
    patch.update(deployed=True, deploymentRecord="DEPLOYMENT.json")
    (HERE / "PATCH.json").write_text(json.dumps(patch, indent=2) + "\n", encoding="utf-8")
    report = dict(utc=datetime.now(timezone.utc).isoformat(), target=str(target),
        installedSHA256=installed, originalSHA256=before, snapshotFiles=len(current),
        snapshotChangedPaths=changed, gameStarted=False, gameStopped=False,
        gameMemoryWritten=False, gameBenefitMeasured=False, baselineRetained=True)
    (HERE / "INSTALL_VERIFIED.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    verification = HERE / "VERIFICATION.txt"
    text = verification.read_text(encoding="utf-8")
    text = text.replace("Production: D89 unchanged; process not called, written, collected, restarted or stopped.",
        "Before cold installation: D89 unchanged; process not called, written, collected, restarted or stopped.")
    text += ("\nCOLD_INSTALL\ncommand=" + subprocess.list2cmdline(argv) +
        "\ninput=Install, production target; game exited normally\nstdout(literal):\n" + stdout +
        "stderr(literal):\n" + stderr + "exitStatus=" + str(result.returncode) +
        "\ninstalledSHA256=" + installed + "\nsnapshotFiles=" + str(len(current)) +
        "\nD89 retained for cold Restore; independently tested rollback behavior remains verified.\n" +
        "Game not started, stopped, collected or written. Game activation/benefit awaits natural startup.\n")
    verification.write_text(text, encoding="utf-8")
    for name in ("MODIFIED_FILE.dll", "DIFF_FILE.patch", "VERIFICATION.txt", "ROLLBACK.sh"):
        assert (HERE / name).read_bytes()
    print(f"COLD_INSTALL_PASS sha256={installed} snapshotFiles={len(current)} artifactsReopened=4 gameStarted=False")


if __name__ == "__main__":
    main()
