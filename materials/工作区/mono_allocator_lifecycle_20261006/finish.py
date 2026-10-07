"""Finalize deployment evidence, concise project state and private-index commit."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parent


def main(stage_only: bool = False) -> None:
    patch = json.loads((HERE/"PATCH.json").read_text(encoding="utf-8"))
    deployment = json.loads((HERE/"DEPLOYMENT.json").read_text(encoding="utf-8-sig"))
    assert deployment["state"] == "disk-installed-snapshot-verified"
    assert deployment["sha256"] == patch["modifiedSHA256"]
    for path in (ROOT/"Mono/EmbedRuntime/mono.dll", WORK/"运行快照/Mono/EmbedRuntime/mono.dll"):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == patch["modifiedSHA256"]
    assert hashlib.sha256((ROOT/"BepInEx/plugins/VaMMemory/VaM.Memory.dll").read_bytes()).hexdigest() == "300d8335a2faedd473a09a0cb27c28df519413ffadf6c4e555f6a3b673278da8"
    verify = HERE/"VERIFICATION.txt"
    text = verify.read_text(encoding="utf-8").split("\nDEPLOYMENT: ")[0].rstrip()+"\n"
    verify.write_text(text, encoding="utf-8")
    with verify.open("a", encoding="utf-8") as f:
        f.write("\nDEPLOYMENT: "+json.dumps(deployment, ensure_ascii=False)+"\n")
        f.write("INSTALL COMMAND (game root): powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\工作区\\mono_allocator_lifecycle_20261006\\install.ps1 -Mode Install\n")
        f.write("LITERAL OUTPUT: SNAPSHOT PASS: 81 files copied and hash-verified; game files read-only\n")
        f.write("LITERAL OUTPUT: INSTALL_PASS mode=Install testCopy=False sha256="+patch["modifiedSHA256"]+" runtimeModified=False\nEXIT STATUS: 0\n")
        f.write("Production and snapshot reopened SHA verified; application memory DLL 1.5.0 unchanged. Next natural startup uses the new file; game behavior/resident convergence unmeasured.\n")
    prefix = patch["modifiedSHA256"][:8].upper()
    note = (f"\n- 2026-10-06 用户场景加载触发 GC heap sections 致命报错，F3F46BBA 拒用；退出后先冷恢复 CD7AB354，再部署修正版 {prefix}。撤销按空闲总量缩小扩堆批量，speculative/fallback 参数恢复原值，4096 项区段表不扩容；小页排序/原合并/前缀提交/256MiB储备保留，lastReturned改为全回调净退提交。实际Mono碎片负载故障版46336项/3914区段提前停止，基线/修正/回滚50000项均82区段；三臂并发/地址/空链/VM/OOM及安装副本恢复通过。81项快照核验、1.5.0应用DLL保持，未自动启停游戏；本次未完成Unity场景加载或驻留验收，见mono_allocator_lifecycle_20261006/REGRESSION.json、VERIFICATION.txt。\n")
    row = f"| Mono 分配/回收策略 | 冷安装修正版 {prefix}；F3F46BBA场景加载触发4096区段上限已拒用。扩堆批量恢复原值，小页pending密度顺序、GC收尾合并、前缀提交及256MiB储备保留。真实Mono区段压力＋三臂通过，下次自然启动生效；实机场景/收敛待验证，CD7AB354恢复入口见mono_allocator_lifecycle_20261006/install.ps1。 |"
    staged_docs = {}
    for name in ("PROJECT_STATE.md", "VAM_MEMORY_REFACTOR.md"):
        path = WORK/name
        current = path.read_text(encoding="utf-8")
        if name == "PROJECT_STATE.md":
            current = "\n".join(row if line.startswith(("| Mono 空闲堆退页 |", "| Mono 分配/回收策略 |")) else line for line in current.split("\n"))
        if note.strip() not in current: current += note
        path.write_text(current, encoding="utf-8")
        base = subprocess.run(["git", "show", "HEAD:"+name], cwd=WORK, capture_output=True, check=True).stdout.decode("utf-8")
        if name == "PROJECT_STATE.md":
            base = "\n".join(row if line.startswith(("| Mono 空闲堆退页 |", "| Mono 分配/回收策略 |")) else line for line in base.split("\n"))
        if note.strip() not in base:
            base += note
        staged_docs[name] = base.encode("utf-8")
    shared = WORK/".git/index"
    original_index = hashlib.sha256(shared.read_bytes()).hexdigest()
    assert original_index == "3ab46b1dfbc71b4abf409f4af9bbe99a97939bbc1a8824e741b2fbfd3afd2321"
    env = {**os.environ, "GIT_INDEX_FILE": str(HERE/"task.index")}

    def git(*args: str, data: bytes | None = None) -> bytes:
        run = subprocess.run(["git", "-c", "gc.auto=0", *args], cwd=WORK, env=env,
                             input=data, capture_output=True)
        assert run.returncode == 0, run.stdout.decode("utf-8", errors="replace")+run.stderr.decode("utf-8", errors="replace")
        return run.stdout

    git("read-tree", "HEAD")
    names = ["audit_binary.py", "AUDIT.json", "BASELINE.dll", "build.py", "BUILD.json", "reclaim_controller.c",
             "MODIFIED_FILE.dll", "PATCH.json", "verify.py", "STRUCTURE.json", "LifecycleSample.cs", "LifecycleSample.dll",
             "RetireSample.cs", "RetireSample.dll", "sample.py", "test_vm.py", "test_suite.py", "lifecycle.py",
             "validate.py", "validate.ps1", "rollback.py", "ROLLBACK.sh", "record.py", "finish.py",
             "DIFF_FILE.patch", "VERIFICATION.txt", "COMMANDS.json", "COMPARISON.json", "README.md", "install.ps1",
             "DEPLOYMENT.json", "DEPLOYMENT_TEST.json", "REGRESSION.json", "sections.py", "REJECTED_SECTIONS.json", ".gitignore", ".gitattributes"]
    for mode in ("BASELINE", "MODIFIED", "ROLLBACK"):
        names.extend(mode+suffix for suffix in ("_RESULT.json", "_RUN.json", "_COMBINED.json", "_LIFECYCLE.json", "_FAILURE.json", "_SECTIONS.json"))
    git("add", "-f", "--", *(str((HERE/name).relative_to(WORK)) for name in names),
        "运行快照/Mono/EmbedRuntime/mono.dll", "运行快照/MANIFEST.json")
    git("update-index", "--chmod=+x", "--", str((HERE/"ROLLBACK.sh").relative_to(WORK)))
    for name, contents in staged_docs.items():
        blob = git("hash-object", "-w", "--stdin", data=contents).decode().strip()
        git("update-index", "--add", "--cacheinfo", "100644,"+blob+","+name)
    review = git("diff", "--cached", "--stat").decode("utf-8", errors="replace")
    print(review, flush=True)
    assert hashlib.sha256(shared.read_bytes()).hexdigest() == original_index
    if stage_only:
        print("STAGE_PASS sharedIndex=unchanged privateIndex=ready")
        return
    git("commit", "-m", "Mono: restore original growth batches after section exhaustion regression")
    commit = git("rev-parse", "HEAD").decode().strip()
    assert hashlib.sha256(shared.read_bytes()).hexdigest() == original_index
    for name in ("MODIFIED_FILE.dll", "DIFF_FILE.patch", "VERIFICATION.txt", "ROLLBACK.sh"):
        assert (HERE/name).read_bytes()
    print("FINAL_PASS deployed=True snapshotFiles=81 artifacts=4 reopened=True sharedIndex=unchanged commit="+commit)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-only", action="store_true")
    main(parser.parse_args().stage_only)
