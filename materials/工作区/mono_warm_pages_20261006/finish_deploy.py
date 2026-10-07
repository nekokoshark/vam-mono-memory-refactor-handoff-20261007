"""Record the cold deployment and only its changed snapshot using a private index."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[1]
NOTE = ("\n- 2026-10-06 用户正常退出后冷安装Mono温区版1C023C25：实际mono.dll/候选/运行快照哈希一致，81项快照复核，仅Mono成员变化；内存应用DLL1.5.0保持。D89可经mono_warm_pages_20261006/install.ps1 -Mode Restore冷恢复，副本原行为回滚已验证。未自动启动游戏，首次自然启动与切换卡顿/增长趋势待用户实测；见INSTALL_VERIFIED.json与VERIFICATION.txt。\n")
ROW = ("| Mono 分配/回收策略 | 冷安装温区版1C023C25：小页按64KiB温区提交，大请求保留精确前缀；原扩堆批量、4096区段表、密度排序/合并和256MiB储备保持。真实Mono三臂及副本恢复通过、81项运行快照核验；游戏未自动启动，切换卡顿/持续增长待实测。D89冷恢复入口：mono_warm_pages_20261006/install.ps1 -Mode Restore。 |")


def updated(text: str, is_project: bool) -> str:
    if is_project:
        text = "\n".join(ROW if line.startswith("| Mono 分配/回收策略 |") else line
                         for line in text.split("\n"))
    if NOTE.strip() not in text:
        text += NOTE
    return text


def main() -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    assert patch["deployed"]
    expected = patch["modifiedSHA256"]
    for path in (ROOT / "Mono/EmbedRuntime/mono.dll", HERE / "MODIFIED_FILE.dll",
                 WORK / "\u8fd0\u884c\u5feb\u7167/Mono/EmbedRuntime/mono.dll"):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    for name in ("deploy.py", "finish_deploy.py"):
        ast.parse((HERE / name).read_text(encoding="utf-8"))
    shared = WORK / ".git/index"
    original = hashlib.sha256(shared.read_bytes()).hexdigest()
    assert original == "3ab46b1dfbc71b4abf409f4af9bbe99a97939bbc1a8824e741b2fbfd3afd2321"
    env = {**os.environ, "GIT_INDEX_FILE": str(HERE / "task.index")}

    def git(*args: str, data: bytes | None = None) -> bytes:
        result = subprocess.run(["git", "-c", "gc.auto=0", *args], cwd=WORK, env=env,
                                input=data, capture_output=True)
        assert result.returncode == 0, result.stdout.decode("utf-8", errors="replace") + result.stderr.decode("utf-8", errors="replace")
        return result.stdout

    git("read-tree", "HEAD")
    names = ("deploy.py", "finish_deploy.py", "PATCH.json", "DEPLOYMENT.json",
             "DEPLOY_COMMAND.json", "INSTALL_VERIFIED.json", "VERIFICATION.txt")
    git("add", "-f", "--", *(str((HERE / name).relative_to(WORK)) for name in names),
        "\u8fd0\u884c\u5feb\u7167/Mono/EmbedRuntime/mono.dll", "\u8fd0\u884c\u5feb\u7167/MANIFEST.json")
    for name in ("PROJECT_STATE.md", "VAM_MEMORY_REFACTOR.md"):
        path = WORK / name
        path.write_text(updated(path.read_text(encoding="utf-8"), name == "PROJECT_STATE.md"), encoding="utf-8")
        base = git("show", "HEAD:" + name).decode("utf-8")
        contents = updated(base, name == "PROJECT_STATE.md").encode("utf-8")
        blob = git("hash-object", "-w", "--stdin", data=contents).decode().strip()
        git("update-index", "--add", "--cacheinfo", "100644," + blob + "," + name)
    print(git("diff", "--cached", "--stat").decode("utf-8", errors="replace"), flush=True)
    assert hashlib.sha256(shared.read_bytes()).hexdigest() == original
    git("commit", "-m", "Mono: cold-install verified 64KiB warm-page runtime after normal game exit")
    assert hashlib.sha256(shared.read_bytes()).hexdigest() == original
    for name in ("MODIFIED_FILE.dll", "DIFF_FILE.patch", "VERIFICATION.txt", "ROLLBACK.sh"):
        assert (HERE / name).read_bytes()
    print("DEPLOY_COMMIT_PASS snapshotFiles=81 sharedIndex=unchanged artifactsReopened=4 gameStarted=False commit=" +
          git("rev-parse", "HEAD").decode().strip())


if __name__ == "__main__":
    main()
