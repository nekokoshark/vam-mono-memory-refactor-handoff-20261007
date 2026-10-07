"""Reproduce the three real arms and reopen the four transaction artifacts."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main() -> None:
    patch = json.loads((HERE/"PATCH.json").read_text(encoding="utf-8"))
    env = {**os.environ, "PYTHON_BIN": sys.executable, "PYTHONIOENCODING": "utf-8",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(ROOT/"tools/pydeps")}
    commands = [("STRUCTURE", [sys.executable, "verify.py"]),
                ("REJECTED", [sys.executable, "sections.py", "REJECTED"]),
                ("BASELINE", ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                               "-File", ".\\validate.ps1", "BASELINE"]),
                ("MODIFIED", ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                               "-File", ".\\validate.ps1", "MODIFIED"]),
                ("ROLLBACK", [r"C:\Program Files\Git\bin\bash.exe", "./ROLLBACK.sh"])]
    records = []
    for mode, argv in commands:
        run = subprocess.run(argv, cwd=HERE, env=env, input="", capture_output=True,
                             text=True, encoding="utf-8", timeout=360)
        records.append(dict(mode=mode, command=subprocess.list2cmdline(argv), cwd=str(HERE),
             input="32MiB pinned + 512MiB temporary; concurrency 4x32; mixed/fragmented/25000 Dispose; 1048576 cells + 262144 refill; 768MiB->300MiB; original OOM; 8192x8KiB holes -> 50000x16KiB retained (4096 section cap)",
             stdin="", stdout=run.stdout, stderr=run.stderr, exitStatus=run.returncode))
        (HERE/"COMMANDS.json").write_text(json.dumps(records, indent=2)+"\n", encoding="utf-8")
        print(run.stdout.strip(), flush=True)
        assert run.returncode == 0, run.stdout + run.stderr
    assert subprocess.run([r"C:\Program Files\Git\bin\bash.exe", "-c", "test -x ./ROLLBACK.sh"], cwd=HERE).returncode == 0
    comparison = {}
    for mode in ("BASELINE", "MODIFIED", "ROLLBACK"):
        runtime = json.loads((HERE/(mode+"_RESULT.json")).read_text(encoding="utf-8"))
        policies = json.loads((HERE/(mode+"_LIFECYCLE.json")).read_text(encoding="utf-8"))
        rows = {r["stage"]: r for r in policies["rows"]}
        before, after = rows["LargeFreeGC3"], rows["ReplaceLarge"]
        final = policies["rows"][-1]["controller"]
        sections = json.loads((HERE/(mode+"_SECTIONS.json")).read_text(encoding="utf-8"))
        comparison[mode] = dict(quickReuseMedianMs=runtime["quickReuseMedianMs"],
            prefixOSCommitIncreaseBytes=after["vm"]["monoCommittedBytes"]-before["vm"]["monoCommittedBytes"],
            prefixHeapIncreaseBytes=after["counters"]["heap"]-before["counters"]["heap"],
            pendingOrder=policies["pendingOrder"], controller=final,
            sparseGCMilliseconds=rows["SparseGC"]["elapsedMs"], refillMilliseconds=rows["RefillCells"]["elapsedMs"],
            retainedSectionTestPayloads=sections["retained"], sectionTestFinalCount=sections["rows"][-1]["sections"])
    comparison["measuredVaMSavingsBytes"] = None
    (HERE/"COMPARISON.json").write_text(json.dumps(comparison, indent=2)+"\n", encoding="utf-8")
    old = (HERE/"BASELINE.dll").read_bytes()
    new = (HERE/"MODIFIED_FILE.dll").read_bytes()
    assert hashlib.sha256(old).hexdigest() == patch["baselineSHA256"]
    assert hashlib.sha256(new).hexdigest() == patch["modifiedSHA256"]
    change = ["Changed branches: GC finish; normal unmapped-block remap/split; both speculative/fallback growth callsites.",
              "Small-object pending reclaim chains: stable descending eight marked-density bands; uncollectable kinds 2/3 retained.",
              "Whole-free mapped/unmapped spans: original merge moved into GC completion before 256MiB reserve retirement.",
              "Normal prefix allocation: native tail header/list bookkeeping, remap only requested prefix; interior blacklist split unchanged.",
              "Growth regression correction: speculative and fallback expansion batches now passed unchanged; numeric observation only. Section table remains 4096 entries; lastReturned is the positive net unmap across merge+retirement.",
              "Original collection trigger, roots, object sizes/addresses, pinning, sweep/clear, TLS lists, locks, blacklist, maximum heap and failure paths retained.",
              "No added explicit game GC, working-set trimming, game start/stop or scene/preset actions. Automatic GC timing can change with heap capacity.",
              "baseline SHA256 "+patch["baselineSHA256"], "modified SHA256 "+patch["modifiedSHA256"],
              "Five original CALLs redirected; RX/RW sections and compiler/thunk unwind added; signing directory cleared."]
    for row in patch["callSites"]:
        change.append(f"RVA 0x{row['rva']:x}: original 0x{row['originalTarget']:x} -> {row['name']} stub 0x{row['stubRVA']:x}")
    source = (HERE/"reclaim_controller.c").read_text(encoding="utf-8")
    change.extend(difflib.unified_diff((HERE.parent/"mono_reclaim_controller_20261006/reclaim_controller.c").read_text(encoding="utf-8").splitlines(),
                  source.splitlines(), fromfile="prior_reclaim_controller.c", tofile="reclaim_controller.c", lineterm=""))
    (HERE/"DIFF_FILE.patch").write_text("\n".join(change)+"\n", encoding="utf-8")
    lines = ["Mono allocation/reclamation policy-layer refactor. Not a replacement marking collector.", *change[:15], "",
             "Changed fields: numeric sort/merge/remap/growth counters and synchronous pending prefix receipt; 29x8 bytes.",
             "Only allocator-owned free spans retire; no active-page compaction or resource/quality change.",
             "Four paths:", *(str(HERE/name) for name in ("MODIFIED_FILE.dll", "DIFF_FILE.patch", "VERIFICATION.txt", "ROLLBACK.sh")), ""]
    for r in records:
        lines.extend([r["mode"]+" COMMAND: "+r["command"], "CWD: "+r["cwd"], "INPUT: "+r["input"],
                      "STDIN: "+repr(r["stdin"]), "LITERAL OUTPUT:", r["stdout"].rstrip(),
                      "STDERR: "+repr(r["stderr"]), "EXIT STATUS: "+str(r["exitStatus"]), ""])
    lines.extend(["ROLLBACK: independent copy restored baseline SHA exactly; original allocation, GC-age and full-remap behavior restored; candidate remains changed.",
                  "Rejected F3F46BBA reproduced section pressure in real Mono; isolated test stops before native fatal limit. No game section count was captured.",
                  "Isolated Windows VM commitment and native unmapped deltas are paired. Not a Unity/VR or real-game memory benefit.",
                  "COMPARISON: "+json.dumps(comparison, sort_keys=True)])
    deployment = HERE/"DEPLOYMENT.json"
    if deployment.exists(): lines.append("DEPLOYMENT: "+deployment.read_text(encoding="utf-8-sig").strip())
    (HERE/"VERIFICATION.txt").write_text("\n".join(lines)+"\n", encoding="utf-8")
    for name in ("MODIFIED_FILE.dll", "DIFF_FILE.patch", "VERIFICATION.txt", "ROLLBACK.sh"):
        assert (HERE/name).read_bytes()
    print("RECORD_PASS artifacts=4 reopened=True rollback=exact candidate=changed")


if __name__ == "__main__":
    main()
