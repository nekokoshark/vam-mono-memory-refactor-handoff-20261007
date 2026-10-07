"""Commit only this task using a private index; leave shared staging untouched."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
NOTE = ("\n- 2026-10-06 用户确认D89基线下降但切换卡顿/持续增长仍在；现场GC最长5645ms，资源卸载亦有6–7s等待。新增64KiB小页温区候选1C023C25，保留大请求精确前缀、原扩堆/4096区段/256MiB储备；三次真实Mono小页对照提交约174731→10931、方法中位9968→850ms（仅helper）。基线/候选/副本回滚七组及安装恢复通过；游戏PID23840仍用D89，未改GC/运行DLL，实际切换收益与上涨根因未确认。候选与命令见mono_warm_pages_20261006/VERIFICATION.txt；冷安装须正常退出。\n")


def main() -> None:
    shared = WORK / ".git/index"
    original = hashlib.sha256(shared.read_bytes()).hexdigest()
    assert original == "3ab46b1dfbc71b4abf409f4af9bbe99a97939bbc1a8824e741b2fbfd3afd2321"
    index = HERE / "task.index"
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}

    def git(*args: str, data: bytes | None = None) -> bytes:
        run = subprocess.run(["git", "-c", "gc.auto=0", *args], cwd=WORK, env=env,
                             input=data, capture_output=True)
        assert run.returncode == 0, run.stdout.decode("utf-8", errors="replace") + run.stderr.decode("utf-8", errors="replace")
        return run.stdout

    git("read-tree", "HEAD")
    files = [p for p in HERE.iterdir() if p.is_file() and p.name != "task.index"
             and not any(p.name.endswith("_" + case + ".json") for case in ("idle", "quick", "stress"))]
    git("add", "-f", "--", *(str(p.relative_to(WORK)) for p in files),
        "mono_allocator_lifecycle_20261006/build.py", "mono_allocator_lifecycle_20261006/verify.py",
        "mono_allocator_lifecycle_20261006/install.ps1")
    git("update-index", "--chmod=+x", "--", "mono_warm_pages_20261006/ROLLBACK.sh")
    for name in ("PROJECT_STATE.md", "VAM_MEMORY_REFACTOR.md"):
        path = WORK / name
        current = path.read_text(encoding="utf-8")
        if NOTE.strip() not in current:
            path.write_text(current + NOTE, encoding="utf-8")
        base = git("show", "HEAD:" + name).decode("utf-8")
        if NOTE.strip() not in base:
            base += NOTE
        blob = git("hash-object", "-w", "--stdin", data=base.encode("utf-8")).decode().strip()
        git("update-index", "--add", "--cacheinfo", "100644," + blob + "," + name)
    print(git("diff", "--cached", "--stat").decode("utf-8", errors="replace"), flush=True)
    assert hashlib.sha256(shared.read_bytes()).hexdigest() == original
    git("commit", "-m", "Mono: batch small-page remaps inside existing reservations; retain cold large tails")
    assert hashlib.sha256(shared.read_bytes()).hexdigest() == original
    for name in ("MODIFIED_FILE.dll", "DIFF_FILE.patch", "VERIFICATION.txt", "ROLLBACK.sh"):
        assert (HERE / name).read_bytes()
    print("COMMIT_PASS sharedIndex=unchanged deployed=False artifacts=4 reopened=True commit=" +
          git("rev-parse", "HEAD").decode().strip())


if __name__ == "__main__":
    main()
