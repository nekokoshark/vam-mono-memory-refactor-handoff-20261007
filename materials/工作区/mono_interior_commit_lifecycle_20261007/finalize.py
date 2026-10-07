"""Reopen real evidence and package the candidate without assuming deployment."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APP_SHA = "300d8335a2faedd473a09a0cb27c28df519413ffadf6c4e555f6a3b673278da8"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name: str):
    return json.loads((HERE / name).read_text(encoding="utf-8-sig"))


def main() -> None:
    patch = read("PATCH.json")
    assert sha(HERE / "BASELINE.dll") == patch["baselineSHA256"]
    assert sha(HERE / "MODIFIED_FILE.dll") == patch["modifiedSHA256"]
    assert sha(ROOT / "BepInEx/plugins/VaMMemory/VaM.Memory.dll") == APP_SHA
    installed = sha(ROOT / "Mono/EmbedRuntime/mono.dll")
    assert installed == patch["modifiedSHA256" if patch["deployed"] else "baselineSHA256"]
    certificates, ordinary = [], {}
    for mode in ("BASELINE", "MODIFIED", "ROLLBACK"):
        certificate, commands = read(mode+"_CERTIFY.json"), read(mode+"_COMMANDS.json")
        assert certificate["stdout"] == mode+"_PASS cases=12" and certificate["exitStatus"] == 0
        assert len(commands) == 12 and all(c["exitStatus"] == 0 for c in commands)
        cases = read(mode+"_INTERIOR.json")
        assert len(cases["rows"]) == 27 and cases["blacklistsRestored"] and cases["originalIATRestored"]
        assert cases["originalInstallHeaderRestored"] and cases["liveAliasesVerified"]
        ordinary[mode] = sum(r["commitBytes"] for r in cases["rows"] if r["label"] in
                            ("cold-small", "cold-large", "cold-nine-pages"))
        abi = read(mode+"_ABI.json")
        assert len(abi["rows"]) == (9 if mode == "MODIFIED" else 6)
        assert all(r["stackRestored"] and r["returnRestored"] for r in abi["rows"])
        certificates.append(certificate)
    assert ordinary == dict(BASELINE=4831838208, MODIFIED=6684672, ROLLBACK=4831838208)
    repeats = read("LIFECYCLE_REPEATS.json")
    assert len(repeats) == 6 and all(r["exitStatus"] == 0 for r in repeats)
    initial = read("INITIAL_LIFECYCLE_FAILURE.json")
    assert initial[-1]["exitStatus"] == 1 and "AssertionError: 0" in initial[-1]["stderr"]
    paths = {name: str(HERE / file) for name, file in (
        ("MODIFIED_FILE", "MODIFIED_FILE.dll"), ("DIFF_FILE", "DIFF_FILE.patch"),
        ("VERIFICATION", "VERIFICATION.txt"), ("ROLLBACK", "ROLLBACK.sh"))}
    result = dict(changedBranch="accepted interior split: whole-span remap -> cold metadata split + common demand commit",
        changedFields="native cold bit on both free spans; first51 state words preserved; append5 interior counters",
        baselineSHA256=patch["baselineSHA256"], modifiedSHA256=patch["modifiedSHA256"],
        paths=paths, certification=certificates, fixtureCommitBytes=ordinary,
        restoredBehavior="independent copy restores B7 and original full interior remap; candidate retained",
        preserved="original blacklist/placement, object identity/content, marking/TLS/locks, OOM, growth batches, 4096 sections, warm64KiB, reserve256MiB",
        installedSHA256=installed, deployed=patch["deployed"], applicationDLLSHA256=APP_SHA,
        originalFailure="one initial large-prefix avoidedBytes assertion saw0; unchanged assertion passed full rerun and three additional candidate runs; cause not established",
        gameBenefitBytes=None, persistentGrowthResolved=False, gameCalls=0, gameWrites=0,
        fixtureLimits="controlled blacklist + isolated long-bucket; cumulative commit flow is not resident/peak savings")
    if patch["deployed"]:
        install = read("INSTALL_VERIFIED.json")
        assert install["snapshotFiles"] == 81 and install["changedMembers"] == ["Mono/EmbedRuntime/mono.dll"]
        assert install["installedSHA256"] == installed
        for row in json.loads((HERE.parent / "运行快照/MANIFEST.json").read_text(encoding="utf-8-sig")):
            assert sha(ROOT / row["Path"]) == row["SHA256"].lower()
            assert sha(HERE.parent / "运行快照" / row["Path"]) == row["SHA256"].lower()
        result["installVerification"] = install
    (HERE / "RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    lines = ["Changed branch: "+result["changedBranch"], "Changed fields: "+result["changedFields"],
        "BASELINE_SHA256="+patch["baselineSHA256"], "MODIFIED_SHA256="+patch["modifiedSHA256"]]
    lines.extend(name+"="+path for name,path in paths.items())
    for c in certificates:
        lines.extend(["", c["mode"], "cwd="+c["workingDirectory"], "command="+c["command"],
            "input="+json.dumps(c["input"]), "stdout(literal)="+c["stdout"], "exitStatus="+str(c["exitStatus"])])
    lines.extend(["", "Restored: "+result["restoredBehavior"], "Preserved: "+result["preserved"],
        "Fixture ordinary cumulative commitment: "+json.dumps(ordinary),
        "27 interior cases: small/large/nine-page lead/exact-right/mapped/noninterior/atomic bypass/header failure/context fallback x3.",
        "27 coalescing cases remain unchanged in all arms; existing concurrency/OOM/section/pending/VM suites retained.",
        "Windows loader + RtlVirtualUnwind restore stack/return at thunk entry/body/epilogue; new thunk carries arg5/base/state as args5/6/7.",
        "Isolated fault: native FirstPart can unlink its free header before returning NULL; fixture repairs only its own list after recording the same failure.",
        "Original blacklists, IAT and InstallHeader entry restored before managed runtime resumes; game not written.",
        "Initial regression observation: "+result["originalFailure"],
        "Full literal nested command outputs/status: BASELINE_COMMANDS.json / MODIFIED_COMMANDS.json / ROLLBACK_COMMANDS.json.",
        "No game resident benefit or persistent-growth cause is established. Do not attribute avoided cumulative flow to physical RAM.",
        "Deployment="+("cold-installed; next natural start" if patch["deployed"] else "candidate-only; running game unchanged"),
        "Atomic install/restore on another copy passed; ROLLBACK.sh does not replace the game.",
        "Production install after normal exit: powershell -NoProfile -File install.ps1 -Mode Install",
        "Cold restore B7 after normal exit: powershell -NoProfile -File install.ps1 -Mode Restore"])
    if patch["deployed"]:
        command = read("DEPLOY_COMMAND.json")
        assert command["exitStatus"] == 0
        lines.extend(["", "COLD_INSTALL", "command="+json.dumps(command["command"],ensure_ascii=False),
            "input="+json.dumps(command["input"]), "stdout(literal):",command["stdout"].rstrip(),
            "exitStatus=0", "installedSHA256="+installed, "81 snapshot files verified; only Mono changed; game not started."])
    (HERE / "VERIFICATION.txt").write_text("\n".join(lines)+"\n", encoding="utf-8")
    (HERE / "README.md").write_text(
        "# Mono 内部取用生命周期重构\n\n"
        "原黑名单选址后，先仅拆分元数据并保留两侧冷状态，再由原共有路径按需提交。不是改GC次数或缩小扩堆。\n"
        "三臂各12组通过；27内部用例和真实Windows展开检查通过。普通组累计提交4.50GiB→6.38MiB→4.50GiB，不等于游戏驻留收益。\n"
        "候选A1A8F07D；"+("已冷安装，下次自然启动生效。" if patch["deployed"] else "尚未安装，运行中的游戏保持B7C1F56D。")+"\n"
        "`install.ps1 -Mode Install/Restore`只在游戏正常退出后替换底层DLL；`ROLLBACK.sh`仅测独立副本。\n"
        "精确路径/命令/初次失败及复跑记录见VERIFICATION.txt。本地接线脚本复用相邻原工程工具；单DLL没有新增外部依赖。\n"
        "参考：[原Mono区段分配源码](https://raw.githubusercontent.com/mono/mono/mono-2-10/libgc/allchblk.c)；实际ABI以AUDIT_INTERIOR.json中的本地DLL为准。\n",
        encoding="utf-8")
    for source in HERE.glob("*.py"):
        content = source.read_text(encoding="utf-8")
        compile(content, str(source), "exec")
        assert len(content.splitlines()) <= 300, source.name
    files = [p for p in HERE.iterdir() if p.is_file() and p.name != "COMMIT_VERIFIED.json"]
    package = ROOT / "Mono_Interior_Commit_Lifecycle_20261007.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(files):
            info = zipfile.ZipInfo(HERE.name+"/"+file.name)
            info.create_system = 3
            info.external_attr = (0o100755 if file.name == "ROLLBACK.sh" else 0o100644)<<16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, file.read_bytes())
    with zipfile.ZipFile(package) as archive:
        assert archive.testzip() is None
        for name,path in paths.items():
            assert archive.read(HERE.name+"/"+Path(path).name) == Path(path).read_bytes()
        assert (archive.getinfo(HERE.name+"/ROLLBACK.sh").external_attr>>16)&0o111
    for path in paths.values(): assert Path(path).read_bytes()
    print(f"ARTIFACTS_PASS reopened=4 packageCRC=pass members={len(files)} deployed={patch['deployed']}")


if __name__ == "__main__":
    main()
