"""Reopen evidence, verify identities, and package the tested local candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8-sig"))
    (HERE / "PATCH.json").write_text(json.dumps(patch, indent=2) + "\n", encoding="utf-8")
    assert sha(HERE / "BASELINE.dll") == patch["baselineSHA256"]
    assert sha(HERE / "MODIFIED_FILE.dll") == patch["modifiedSHA256"]
    assert sha(HERE / "rollback_copy/mono.dll") == patch["baselineSHA256"]
    assert sha(HERE / "deployment_test/mono.dll") == patch["baselineSHA256"]
    deployed = patch["deployed"]
    assert sha(ROOT / "Mono/EmbedRuntime/mono.dll") == patch["modifiedSHA256" if deployed else "baselineSHA256"]
    install = None
    if deployed:
        install = json.loads((HERE / "INSTALL_VERIFIED.json").read_text(encoding="utf-8-sig"))
        assert install["snapshotVerified"] and install["snapshotFiles"] == 81
        assert install["changedMembers"] == ["Mono/EmbedRuntime/mono.dll"]
        assert sha(ROOT / "BepInEx/plugins/VaMMemory/VaM.Memory.dll") == install["appDLLSHA256"]
    old = (HERE.parent / "mono_warm_pages_20261006/reclaim_controller.c").read_text(encoding="utf-8")
    new = (HERE / "reclaim_controller.c").read_text(encoding="utf-8")
    marker = "/* This call site is followed immediately by take_prefix"
    assert old.split(marker, 1)[1] == new.split(marker, 1)[1], "Unrelated policies changed"
    for source in HERE.glob("*.py"):
        code = source.read_text(encoding="utf-8")
        compile(code, str(source), "exec")
        assert len(code.splitlines()) <= 300
    paths = {name: str(HERE / filename) for name, filename in (
        ("MODIFIED_FILE", "MODIFIED_FILE.dll"), ("DIFF_FILE", "DIFF_FILE.patch"),
        ("VERIFICATION", "VERIFICATION.txt"), ("ROLLBACK", "ROLLBACK.sh"))}
    certificates = []
    for mode in ("BASELINE", "MODIFIED", "ROLLBACK"):
        certificate = json.loads((HERE / (mode + "_CERTIFY.json")).read_text(encoding="utf-8-sig"))
        commands = json.loads((HERE / (mode + "_COMMANDS.json")).read_text(encoding="utf-8"))
        assert certificate["exitStatus"] == 0 and certificate["stdout"] == mode + "_PASS cases=9"
        assert len(commands) == 9 and all(c["exitStatus"] == 0 for c in commands)
        certificates.append(certificate)
    cohort = {m: json.loads((HERE / (m + "_COHORT.json")).read_text(encoding="utf-8"))
              for m in ("BASELINE", "MODIFIED", "ROLLBACK")}
    samples = {}
    for mode, report in cohort.items():
        sparse = next(r for r in report["rows"] if r["stage"] == "SparseGC")
        before = report["rows"][0]
        varied = [r for r in sparse["chains"] if sum(x > 0 for x in r["bands"]) >= 3 and r["pages"] > 1000]
        samples[mode] = dict(pendingPages=sparse["pendingPages"], invalidHeaders=sparse["invalid"],
            independentInversions=sum(r["inversions"] for r in varied),
            rejects=sparse["state"]["rejected"]-before["state"]["rejected"],
            gcMs=sparse["elapsedMs"], heapBytes=sparse["heap"], sections=sparse["sections"])
    assert samples["BASELINE"]["rejects"] > 0 and samples["ROLLBACK"]["rejects"] > 0
    assert samples["MODIFIED"]["rejects"] == samples["MODIFIED"]["independentInversions"] == 0
    result = dict(changedBranch="order_reclaim: global admission -> independent kind/size validation",
        changedFields="page_bound=registered object heap/4096; first32 state words preserved; append11 words",
        preserved="marking, object identity, TLS/locks, blacklist, original growth, section limit4096, warm64KiB, reserve256MiB",
        baselineSHA256=patch["baselineSHA256"], modifiedSHA256=patch["modifiedSHA256"],
        paths=paths, certification=certificates, independentRegression=samples,
        copyRollback="1C hash and original global-reject/native-fallback behavior restored",
        gameDiskModified=deployed, gameMemoryWrites=0, gameMethodCalls=0, deployed=deployed,
        installVerified=install, gameBenefitBytes=None,
        attribution="global-cap defect demonstrated in isolated real Mono; current game rejection cause remains unconfirmed",
        timing="single helper observations, not stable acceleration or game performance",
        captureStatus="syntax checked; candidate-specific live capture awaits natural startup")
    (HERE / "RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["Changed branch: " + result["changedBranch"], "Changed fields: " + result["changedFields"],
             "Preserved: " + result["preserved"], "BASELINE_SHA256=" + patch["baselineSHA256"],
             "MODIFIED_SHA256=" + patch["modifiedSHA256"]]
    lines.extend(name + "=" + value for name, value in paths.items())
    for c in certificates:
        lines.extend(["", c["mode"], "cwd=" + c["workingDirectory"], "command=" + c["command"],
            "input=" + json.dumps(c["input"]), "stdout(literal)=" + c["stdout"],
            "exitStatus=" + str(c["exitStatus"])])
    lines.extend(["", "Restored: independent copy retains original 1C global-reject/native-fallback behavior; candidate remains changed.",
        "Nine cases/arm: idle, quick, stress, lifecycle, original OOM, fragmented sections, warm pages, >1M pending pages, size/mark/cycle isolation.",
        "Fault injections are confined to a private helper; native state is restored before managed execution resumes.",
        "Whole-free merge/retirement, remap prefix, original expansion batches and 4096 section limit remain unchanged.",
        "Independent regression: " + json.dumps(samples, ensure_ascii=False),
        "No heap-growth/physical-memory benefit is established: fixture refills do not expand the heap in either arm.",
        "The observed game rejection count lacks a cause; this defect is not an attribution of the game's GiB slope.",
        "Application DLL1.5.0 unchanged; no game start/stop/GC/WS trim/process-memory writes.",
        ("Cold installed after user normal exit; 81 snapshot members verified, only Mono changed. Natural startup/benefit not yet verified."
         if deployed else "Candidate ready for cold installation after normal exit. No runtime snapshot update required before deployment."),
        "Allocator reference: https://hboehm.info/gc/gcdescr.html (context only; native ABI comes from the audited local DLL)."])
    if deployed:
        command = json.loads((HERE / "DEPLOY_COMMAND.json").read_text(encoding="utf-8-sig"))
        assert command["exitStatus"] == 0
        lines.extend(["", "COLD_INSTALL", "command=" + command["command"],
            "input=" + json.dumps(command["input"]), "stdout(literal):", command["stdout"],
            "exitStatus=" + str(command["exitStatus"]), "installedSHA256=" + install["installedSHA256"]])
    (HERE / "VERIFICATION.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (HERE / "README.md").write_text(
        "# Mono 队列复用候选\n\n"
        "重构 order_reclaim：按 kind/size 独立核查、按已注册堆页数限制遍历、同密度链跳过重排。\n"
        "四项原策略及应用 DLL1.5.0 保持，测试详情见 VERIFICATION.txt。\n" +
        ("用户正常退出后已冷安装并核验81项快照；下次自然启动加载。尚无游戏内存收益结论。\n\n" if deployed
         else "这是现有本地工作区的候选，不是已经激活的游戏版本；尚无游戏内存收益结论。\n\n") +
        "游戏正常退出后，在此目录运行 `powershell -NoProfile -File install.ps1 -Mode Install`。\n"
        "冷恢复1C使用 `-Mode Restore`。安装器复用相邻已审查工具并更新运行快照。\n"
        "`ROLLBACK.sh`只恢复并测试独立副本，保留候选；它不替换游戏。\n"
        "新版本自然启动后的固定字段采样：`python capture.py PID`，不调用游戏方法或扫描对象内容。\n",
        encoding="utf-8")
    package = ROOT / "Mono_Reclaim_Cohorts_20261006.zip"
    members = ["MODIFIED_FILE.dll", "BASELINE.dll", "DIFF_FILE.patch", "VERIFICATION.txt", "ROLLBACK.sh",
        "rollback.py", "install.ps1", "PATCH.json", "RESULT.json", "README.md", "reclaim_controller.c",
        "build.py", "CERTIFY.ps1", "validate.py", "run_case.py", "capture.py", "PendingCohort.cs",
        "cohort_test.py", "isolation_test.py", "pending_probe.c", "probe_build.py", "finalize.py"]
    if deployed:
        members.extend(["INSTALL_VERIFIED.json", "DEPLOY_COMMAND.json"])
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in members:
            archive.write(HERE / name, HERE.name + "/" + name)
    with zipfile.ZipFile(package) as archive:
        assert archive.testzip() is None
        assert hashlib.sha256(archive.read(HERE.name + "/MODIFIED_FILE.dll")).hexdigest() == patch["modifiedSHA256"]
    for path in paths.values():
        assert Path(path).read_bytes()
    print(f"ARTIFACTS_PASS reopened=4 packageCRC=pass members={len(members)} candidateRetained=True deployed={deployed}")


if __name__ == "__main__":
    main()
