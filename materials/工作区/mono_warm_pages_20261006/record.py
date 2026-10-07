"""Run three real-runtime arms and copy installation; reopen four deliverables."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LEGACY = HERE.parent / "mono_allocator_lifecycle_20261006"
ARTIFACTS = ("MODIFIED_FILE.dll", "DIFF_FILE.patch", "VERIFICATION.txt", "ROLLBACK.sh")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    production = ROOT / "Mono/EmbedRuntime/mono.dll"
    assert digest(production) == patch["baselineSHA256"]
    commands = []

    def run(name, argv, inputs, env=None):
        result = subprocess.run(argv, cwd=HERE, env=env, capture_output=True, text=True, timeout=240)
        commands.append(dict(name=name, argv=argv, cwd=str(HERE), input=inputs,
                             stdout=result.stdout, stderr=result.stderr, exitStatus=result.returncode))
        (HERE / "COMMANDS.json").write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
        print(result.stdout.rstrip(), flush=True)
        assert result.returncode == 0, result.stderr

    for mode in ("BASELINE", "MODIFIED"):
        run(mode, [sys.executable, str(HERE / "validate.py"), mode],
            dict(mode=mode, runtime="task-local real Mono", cases="idle, quick, stress, lifecycle, OOM, section fragments, small pages"))
    env = {**os.environ, "PYTHON": sys.executable.replace("\\", "/")}
    run("ROLLBACK", [r"C:\Program Files\Git\bin\bash.exe", str(HERE / "ROLLBACK.sh")],
        dict(copy="candidate -> baseline D89", cases="same seven real-runtime cases"), env=env)
    test = HERE / "deployment_test/mono.dll"
    test.parent.mkdir(exist_ok=True)
    shutil.copy2(HERE / "BASELINE.dll", test)
    for mode in ("Install", "Restore"):
        run("COPY_" + mode.upper(), ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(HERE / "install.ps1"), "-Mode", mode, "-TestCopy"], dict(target=str(test)))
    assert digest(test) == patch["baselineSHA256"]
    assert digest(HERE / "rollback_copy/mono.dll") == patch["baselineSHA256"]
    assert digest(HERE / "MODIFIED_FILE.dll") == patch["modifiedSHA256"]
    assert digest(production) == patch["baselineSHA256"]
    diff = (f"BASELINE_SHA256 {patch['baselineSHA256']}\n"
            f"MODIFIED_SHA256 {patch['modifiedSHA256']}\n"
            "Changed branch: take_prefix / need < 65536 / bounded warm prefix and cold tail\n\n")
    diff += "".join(difflib.unified_diff(
        (LEGACY / "reclaim_controller.c").read_text(encoding="utf-8").splitlines(True),
        (HERE / "reclaim_controller.c").read_text(encoding="utf-8").splitlines(True),
        fromfile="D89/reclaim_controller.c", tofile="candidate/reclaim_controller.c"))
    # The shared index is intentionally preserved and can precede HEAD. Compare
    # explicit committed files, not that index, when describing our own edits.
    for name in ("build.py", "verify.py", "install.ps1"):
        relative = "mono_allocator_lifecycle_20261006/" + name
        before = subprocess.run(["git", "show", "HEAD:" + relative], cwd=HERE.parent,
                                capture_output=True, check=True).stdout.decode("utf-8")
        diff += "\n" + "".join(difflib.unified_diff(before.splitlines(True),
            (LEGACY / name).read_text(encoding="utf-8").splitlines(True),
            fromfile="HEAD/" + relative, tofile=relative))
    (HERE / "DIFF_FILE.patch").write_text(diff, encoding="utf-8")
    performance = json.loads((HERE / "PERFORMANCE.json").read_text(encoding="utf-8"))["summary"]
    report = ["Changed branch: take_prefix / need < 65536 / warm prefix, cold tail\n",
        "Fields appended: warmBatches, warmBytes, warmExtraBytes; first 29 words preserved.\n",
        "Large requests, original expansion arguments, section limit4096 and reserve256MiB preserved.\n",
        "Production: D89 unchanged; process not called, written, collected, restarted or stopped.\n",
        "GC OS roots include scratch/header storage outside the registered object heap.\n",
        "VM closure tests equate reserved OS pages to native unmapped bytes, not total commitment to heap.\n",
        "Restored behavior/status: independent copy returns to D89 exact hash, original prefix behavior and all seven tests pass; candidate remains changed.\n",
        "Rollback here tests only a separate copy. Cold production restore uses install.ps1 -Mode Restore after normal game exit.\n\n"]
    for name in ARTIFACTS:
        report.append(name + "=" + str(HERE / name) + "\n")
    for command in commands:
        report.extend(["\n" + command["name"] + "\n",
            "cwd=" + command["cwd"] + "\n",
            "command=" + subprocess.list2cmdline(command["argv"]) + "\n",
            "input=" + json.dumps(command["input"]) + "\n",
            "stdout(literal):\n" + command["stdout"],
            "stderr(literal):\n" + command["stderr"],
            "exitStatus=" + str(command["exitStatus"]) + "\n"])
    report.append("\nHelper performance only (three alternating runs):\n" + json.dumps(performance, indent=2) + "\n")
    report.append("No game stutter/first-ready growth benefit has been measured for this candidate.\n")
    (HERE / "VERIFICATION.txt").write_text("".join(report), encoding="utf-8")
    for name in ARTIFACTS:
        assert (HERE / name).read_bytes(), name
    subprocess.run([r"C:\Program Files\Git\bin\bash.exe", "-n", str(HERE / "ROLLBACK.sh")], check=True)
    print("TRANSACTION_PASS artifacts=4 reopened=True baseline=D89 rollback=D89 candidate=changed gameModified=False")


if __name__ == "__main__":
    main()
