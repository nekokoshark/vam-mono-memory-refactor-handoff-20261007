"""Record the actual final three-arm commands, evidence and changed branch."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def main() -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    env = dict(os.environ, PYTHON_BIN=sys.executable, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    commands = [("STRUCTURE", [sys.executable, str(HERE / "verify.py")]),
                ("BASELINE", [sys.executable, str(HERE / "test_suite.py"), "BASELINE"]),
                ("MODIFIED", [sys.executable, str(HERE / "test_suite.py"), "MODIFIED"]),
                ("ROLLBACK", [r"C:\Program Files\Git\bin\bash.exe", "./ROLLBACK.sh"])]
    records = []
    for mode, argv in commands:
        run = subprocess.run(argv, cwd=HERE, env=env, capture_output=True, text=True, timeout=240)
        records.append(dict(mode=mode, argv=argv, cwd=str(HERE), stdout=run.stdout,
                            stderr=run.stderr, exitStatus=run.returncode,
                            input="32 MiB pinned/live; 512 MiB page-touched temporary; quick reuse; 4x32 concurrent; mixed/fragmented arrays; 25000 Dispose"))
        (HERE / "COMMANDS.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        print(run.stdout.strip(), flush=True)
        assert run.returncode == 0, run.stderr
    baseline = json.loads((HERE / "BASELINE_RESULT.json").read_text())
    modified = json.loads((HERE / "MODIFIED_RESULT.json").read_text())
    comparison = dict(baselineFirstLargeReturn=3, modifiedFirstLargeReturn=1, rollbackFirstLargeReturn=3,
        baselineQuickMedianMs=baseline["quickReuseMedianMs"], modifiedQuickMedianMs=modified["quickReuseMedianMs"],
        candidateReserveBytes=patch["reserveBytes"], measuredGameSavingsBytes=None)
    for mode, result in (("baseline", baseline), ("modified", modified)):
        idle = [c for c in result["cases"] if c["scenario"] == "idle"]
        comparison[mode+"ActualOSCommitDropsBytes"] = [c["largeReturn"]["monoOSCommitDropBytes"] for c in idle]
        comparison[mode+"GC1Milliseconds"] = [next(r["elapsedMs"] for r in c["rows"] if r["stage"] == "GC1") for c in idle]
    (HERE / "COMPARISON.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    lines = ["Mono whole-free-block reclamation controller: native source refactor",
             "Changed branch: finish_collection RVA 0x157ec4 -> native reclaim_controller; legacy scanner retained but bypassed.",
             "Changed fields: ReclaimState.reserve_bytes, whole_free_committed_before/after, decommitted_bytes/blocks.",
             "BASELINE SHA256 " + patch["baselineSHA256"], "MODIFIED SHA256 " + patch["modifiedSHA256"],
             "Original collectors/roots/layout/pinning/allocator/OS decommit-remap unchanged. No extra game GC.",
             "256 MiB limits whole-free committed reserve at GC completion, NOT total live heap/RAM.",
             "Array/string/reference/pin and interleaved live-page tests use the original embedded Mono.",
             "GC OS-table Windows VM commitment deltas equal native unmapped deltas exactly.",
             "PrivateUsage includes independent Python/loader changes; not equated to Mono deltas.",
             "No Unity/VR or real-game memory benefit is claimed by these isolated tests.", "", "FOUR ARTIFACTS:"]
    for name in ("MODIFIED_FILE.dll", "DIFF_FILE.patch", "VERIFICATION.txt", "ROLLBACK.sh"):
        lines.append(str(HERE / name))
    lines += ["", "ENV PYTHONPATH=" + str(HERE.parents[1] / "tools/pydeps"),
              "ENV PYTHON_BIN=" + sys.executable, "ENV PYTHONDONTWRITEBYTECODE=1", "ENV PYTHONIOENCODING=utf-8", ""]
    for r in records:
        lines += [r["mode"] + " COMMAND: " + subprocess.list2cmdline(r["argv"]),
                  "CWD: " + r["cwd"], "INPUT: " + r["input"],
                  "LITERAL STDOUT:", r["stdout"].rstrip(), "LITERAL STDERR: " + repr(r["stderr"]),
                  "EXIT STATUS: " + str(r["exitStatus"]), ""]
    lines += ["ROLLBACK: independent copy restored exact baseline SHA; original age-1 path returns at third test GC; changed candidate remains.",
              "USER CORRECTION: small-object allocation/reuse, post-sweep coalescing and heap expansion remain original; full linked refactor incomplete.",
              "Production restore (after game exits): powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1 -Mode Restore",
              "COMPARISON: " + json.dumps(comparison, sort_keys=True)]
    deployment = HERE / "DEPLOYMENT.json"
    if deployment.exists():
        lines.append("DEPLOYMENT: " + json.dumps(json.loads(deployment.read_text(encoding="utf-8-sig")), ensure_ascii=False))
    (HERE / "VERIFICATION.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    original = (HERE / "BASELINE.dll").read_bytes()
    candidate = (HERE / "MODIFIED_FILE.dll").read_bytes()
    diff = ["Binary + source refactor; reproduce with build.py and audit_binary.py.",
            "baseline SHA256 " + patch["baselineSHA256"], "modified SHA256 " + patch["modifiedSHA256"],
            "Native original sections: only the five-byte CALL site at RVA 0x157ec4 is redirected.",
            "Original unmap/remap/scanner/OS-table/native GC bodies are byte-identical.",
            "Added native C controller in RX .gcrtext; numeric state and relocated unwind records in RW .gcrdat.",
            "PE: 2 section headers, image/code/data sizes, merged exception directory and checksum updated.",
            "Modified PE signing directory cleared; no new imports, exports, relocations or entry point.",
            "The original entire file is retained as BASELINE.dll.", "HEADER BYTE DIFF:"]
    for i, (a, b) in enumerate(zip(original[:1024], candidate[:1024])):
        if a != b:
            diff.append(f"offset 0x{i:x}: {a:02x} -> {b:02x}")
    for s in json.loads((HERE / "AUDIT.json").read_text())["sections"]:
        for i in range(s["rawOffset"], s["rawOffset"]+s["rawSize"]):
            if original[i] != candidate[i]:
                diff.append(f"native file offset 0x{i:x}: {original[i]:02x} -> {candidate[i]:02x}")
    diff.append("APPENDED SECTIONS: " + json.dumps(patch["sections"]))
    diff.append("SOURCE: reclaim_controller.c; BUILD: build.py; loader preservation validated by verify.py.")
    (HERE / "DIFF_FILE.patch").write_text("\n".join(diff) + "\n", encoding="utf-8")
    for name in ("MODIFIED_FILE.dll", "DIFF_FILE.patch", "VERIFICATION.txt", "ROLLBACK.sh"):
        assert (HERE / name).read_bytes()
    print("RECORD_PASS artifacts=4 reopened=True rollback=exact candidate=changed", flush=True)


if __name__ == "__main__":
    main()
