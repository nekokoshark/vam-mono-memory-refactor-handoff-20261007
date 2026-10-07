"""Reopen real artifacts and package observed certification, not game savings."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODES = ("BASELINE", "MODIFIED", "ROLLBACK")
PACKAGE = ROOT / "Mono_Warm_Reuse_Lifecycle_20261007.zip"
INPUT = "idle quick stress lifecycle failure sections warm reuse cohort isolation spans interior ABI"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    artifacts = ("MODIFIED_FILE.dll", "DIFF_FILE.patch", "VERIFICATION.txt", "ROLLBACK.sh")
    assert digest(HERE / "BASELINE.dll") == patch["baselineSHA256"]
    assert digest(HERE / "MODIFIED_FILE.dll") == patch["modifiedSHA256"]
    assert digest(HERE / "rollback_copy/mono.dll") == patch["baselineSHA256"]
    # Packaging itself does not perform a live deployment.
    installed_hash = digest(ROOT / "Mono/EmbedRuntime/mono.dll")
    assert installed_hash in (patch["baselineSHA256"], patch["modifiedSHA256"])
    deployed = installed_hash == patch["modifiedSHA256"]
    status = "Mono 小对象页取用生命周期已冷安装 D4685C71；下次自然启动生效。" if deployed else "Mono 小对象页取用生命周期候选；未替换正在运行的游戏。"
    certification = {}
    for mode in MODES:
        record = json.loads((HERE / f"{mode}_CERTIFY.json").read_text(encoding="utf-8-sig"))
        commands = json.loads((HERE / f"{mode}_COMMANDS.json").read_text(encoding="utf-8"))
        assert record["exitStatus"] == 0 and record["stdout"] == f"{mode}_PASS cases=13"
        assert len(commands) == 13 and all(r["exitStatus"] == 0 for r in commands)
        assert [r["input"]["test"] for r in commands] == INPUT.split()
        reuse = json.loads((HERE / f"{mode}_REUSE.json").read_text(encoding="utf-8"))
        expected = 0 if mode == "MODIFIED" else 65536
        assert reuse["rows"][0]["nativeCommitBytes"] == expected
        certification[mode] = record

    lines = [status,
        "CHANGED_BRANCH: GC_new_hblk RVA 0x161EBA -> reuse_small -> original GC_allochblk_nth / full-search fallback",
        "CHANGED_FIELDS: original 56 state words preserved; six counters at word 56; 32 complemented non-owning hints at word 62.",
        f"BASELINE_SHA256: {patch['baselineSHA256']}",
        f"MODIFIED_SHA256: {patch['modifiedSHA256']}",
        ""]
    lines.extend(f"{name}: {HERE / name}" for name in artifacts)
    lines.extend(["", f"WORKING_DIRECTORY: {HERE}", f"INPUT: {INPUT}; isolated original Mono children; no game calls/writes."])
    for mode, record in certification.items():
        lines.extend(["", f"{mode} COMMAND: {record['command']}",
            f"{mode} INPUT: mode={mode}; same 13 isolated cases above.",
            f"{mode} LITERAL_STDOUT: {record['stdout']}", f"{mode} EXIT_STATUS: {record['exitStatus']}",
            f"{mode} NESTED_COMMANDS_AND_LITERAL_OUTPUTS: {HERE / (mode + '_COMMANDS.json')}"])
    lines.extend(["", "RESTORED_BEHAVIOR: rollback_copy/mono.dll hashes to A1A8F07D; same 13 tests pass; normal fixture commits 65536 B again.",
        "CANDIDATE_STATUS: MODIFIED_FILE.dll remains D4685C71; its normal fixture commits 0 B; blacklisted fixture commits 4096 B versus 65536 B baseline/rollback.",
        "DEPLOYMENT_COPY_RESULT: Install/Restore exit 0; restored A1A8F07D. Historical pre-exit Check: INSTALL_PENDING gameRunning=True diskModified=False, exit 2.",
        "PRESERVED: original marking/locks/live aliases/blacklists/OOM/expansion arguments/4096 sections; A1 retire, sort, merge, interior and 64-KiB quantum policies.",
        "FIXTURE_NOT_GAME_SAVINGS: 64-KiB avoided commitment is a constructed native allocation test, not physical-RAM benefit or proof that continuous growth is solved.",
        "TIMING: one-run warm fixture retains 10931 cold remaps in all arms; no game loading/frame-time benefit asserted.",
        "ROLLBACK.sh is executable under Git Bash; CERTIFY ROLLBACK executes test -x and the script before validation.",
        "INSTALL/RESTORE: install.ps1 -Mode Install/Restore, only after normal game exit. These local tools reuse adjacent audited engineering projects.",
        f"PACKAGE: {PACKAGE}"])
    if deployed:
        install = json.loads((HERE / "INSTALL_COMMAND.json").read_text(encoding="utf-8-sig"))
        verified = json.loads((HERE / "INSTALL_VERIFIED.json").read_text(encoding="utf-8"))
        assert install["exitStatus"] == 0 and verified["installedSHA256"] == installed_hash
        assert verified["snapshotFilesVerified"] == 81 and not verified["gameRunning"]
        lines.extend([f"INSTALL COMMAND: {install['command']}", "INSTALL INPUT: mode=Install; testCopy=False; gameExited=True.",
            f"INSTALL LITERAL_OUTPUT: {install['literalOutput']}", "INSTALL EXIT_STATUS: 0",
            "INSTALLED_STATUS: production/candidate/snapshot hashes match D4685C71; no game started; cold restore remains A1A8F07D."])
    (HERE / "VERIFICATION.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    readme = f"""# Mono 小对象页复用生命周期候选

{status} 本次冷恢复基线为 A1A8F07D。

## 改造对比
- 原路径：小对象需要新页时，按原空闲桶搜索，可能先取冷块。
- 新路径：先验证最多 32 个已提交空闲块提示，再交给原 nth 分配器；没有成功提示就回原完整搜索。
- 提示不拥有对象，地址按位取反；每次取用重新核对字段与双向链，原黑名单/拆分/计账继续执行。
- 原 56 个状态字段保持顺序和类型；追加 6 个计数器、32 个提示，共 94 个 64 位字。
- 原 GC、锁、对象/像素语义、扩堆和 4096 区段上限均保持。没有增加 GC、调小扩堆批量或每帧扫描。

## 证据
基线/候选/副本回滚各 13 组原 Mono 测试通过。专门复用夹具的相同分配负载新增提交为 65536/0/65536 B。
普通 warm 夹具仍为 10931 次 cold remap；一次耗时不作为加速结论。尚无游戏峰值、立即返回水位或持续增长斜率的候选实测。
现场累计退提交约 89 GiB、前缀重提交约 91 GiB，是先前 A1 会话的流量，不是物理节省或波动的完整归因。

## 文件和使用
部署产物是 MODIFIED_FILE.dll；正常退出后由本地 install.ps1 冷替换 Mono\\EmbedRuntime\\mono.dll。
恢复本次基线用 install.ps1 -Mode Restore；ROLLBACK.sh 只恢复独立测试副本并验证，不修改游戏。
不自动停止/启动游戏。Mono 底层更新与 VaM.Memory.dll 1.5.0 独立，本次没有修改后者。

四工件、精确测试命令/输入/原样输出/退出码及恢复状态见 VERIFICATION.txt；嵌套命令在 *_COMMANDS.json。
DLL 是单文件替换产物；源码构建、安装和复验工具复用本地相邻工程与游戏托管库，ZIP 不代表独立移植构建环境。
包位置：{PACKAGE}

原源码对照：[Mono allchblk.c](https://raw.githubusercontent.com/mono/mono/mono-2-10/libgc/allchblk.c)、[隐藏指针契约](https://raw.githubusercontent.com/mono/mono/mono-2-10/libgc/include/gc.h)。实际本地 DLL 审计决定 ABI。
"""
    (HERE / "README.md").write_text(readme, encoding="utf-8")
    members = ["BASELINE.dll", "MODIFIED_FILE.dll", "BASELINE_PATCH.json", "PATCH.json", "STRUCTURE.json",
        "BUILD.json", "LIVE_COUNTERS.json", "README.md", "VERIFICATION.txt", "DIFF_FILE.patch", "reclaim_controller.c",
        "prepare.py", "build.py", "verify.py", "test_reuse.py", "run_case.py", "validate.py", "rollback.py",
        "ROLLBACK.sh", "CERTIFY.ps1", "install.ps1", "finalize.py"]
    members += [f"{mode}_{kind}.json" for mode in MODES for kind in ("CERTIFY", "COMMANDS", "REUSE")]
    if deployed:
        members += ["DEPLOYMENT.json", "INSTALL_COMMAND.json", "INSTALL_VERIFIED.json", "verify_install.py"]
    manifest = {name: dict(bytes=(HERE / name).stat().st_size, sha256=digest(HERE / name)) for name in members}
    with zipfile.ZipFile(PACKAGE, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in members:
            archive.write(HERE / name, name)
        archive.writestr("MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    with zipfile.ZipFile(PACKAGE) as archive:
        assert archive.testzip() is None
        for name, row in manifest.items():
            data = archive.read(name)
            assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
    for name in artifacts:
        assert (HERE / name).read_bytes()
    (HERE / "PACKAGE.json").write_text(json.dumps(dict(path=str(PACKAGE), sha256=digest(PACKAGE),
        bytes=PACKAGE.stat().st_size, crcVerified=True, members=len(members) + 1,
        reopenedArtifacts=list(artifacts), coldInstalled=deployed, installedSHA256=installed_hash,
        gameStarted=False), indent=2) + "\n", encoding="utf-8")
    print(f"PACKAGE_PASS members={len(members) + 1} CRC=verified artifacts=4-reopened coldInstalled={deployed} gameStarted=False")


if __name__ == "__main__":
    main()
