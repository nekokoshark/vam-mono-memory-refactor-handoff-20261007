"""Verify the cold deployment, reopen evidence, and package the local integration."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ROOT = REPO.parent
APP_SHA = "300d8335a2faedd473a09a0cb27c28df519413ffadf6c4e555f6a3b673278da8"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name: str):
    return json.loads((HERE / name).read_text(encoding="utf-8-sig"))


def main() -> None:
    patch = read("PATCH.json")
    assert sha(HERE / "BASELINE.dll") == patch["baselineSHA256"]
    assert sha(HERE / "MODIFIED_FILE.dll") == patch["modifiedSHA256"]
    for directory in ("rollback_copy", "deployment_test"):
        copy = HERE / directory / "mono.dll"
        if copy.exists(): assert sha(copy) == patch["baselineSHA256"]
    command = read("DEPLOY_COMMAND.json")
    assert command["exitStatus"] == 0
    assert sha(ROOT / "Mono/EmbedRuntime/mono.dll") == patch["modifiedSHA256"]
    assert sha(ROOT / "BepInEx/plugins/VaMMemory/VaM.Memory.dll") == APP_SHA
    manifest = json.loads((REPO / "运行快照/MANIFEST.json").read_text(encoding="utf-8-sig"))
    old_bytes = subprocess.check_output(["git", "-C", str(REPO), "show", "HEAD:运行快照/MANIFEST.json"])
    prior_install = HERE / "INSTALL_VERIFIED.json"
    saved = read("INSTALL_VERIFIED.json") if prior_install.exists() else {}
    previous = saved.get("previousSnapshotHashes") or {r["Path"]: r["SHA256"].lower() for r in json.loads(old_bytes.decode("utf-8-sig"))}
    assert len(manifest) == 81 and set(previous) == {r["Path"] for r in manifest}
    changed = []
    for row in manifest:
        name, digest = row["Path"], row["SHA256"].lower()
        assert sha(ROOT / name) == digest == sha(REPO / "运行快照" / name)
        if digest != previous[name]: changed.append(name)
    assert changed == ["Mono/EmbedRuntime/mono.dll"]
    install = dict(installedSHA256=patch["modifiedSHA256"],snapshotVerified=True,snapshotFiles=81,
                   changedMembers=changed,appDLLSHA256=APP_SHA,runtimeStartedByAgent=False,previousSnapshotHashes=previous)
    (HERE / "INSTALL_VERIFIED.json").write_text(json.dumps(install,indent=2)+"\n")
    patch.update(deployed=True,deploymentRecord="DEPLOYMENT.json")
    (HERE / "PATCH.json").write_text(json.dumps(patch,indent=2)+"\n")
    before = (REPO / "mono_reclaim_cohorts_20261006/reclaim_controller.c").read_text()
    after = (HERE / "reclaim_controller.c").read_text()
    # Sorting, demand remap, warm64KiB, native growth and retirement stay identical.
    first = "/* Native header marks occupy eight words"
    last = "/* Coalescing storage is one budgeted transaction"
    assert before.split(first)[1].split("/* Preserve warm reusable storage.")[0] == after.split(first)[1].split(last)[0]
    assert before.split("    /* Pass 0: older whole-free blocks.")[1] == after.split("    /* Pass 0: older whole-free blocks.")[1]
    sources = list(HERE.glob("*.py"))
    for source in sources:
        content = source.read_text(encoding="utf-8")
        compile(content,str(source),"exec")
        assert len(content.splitlines()) <= 300
    certificates, spans, small = [], {}, {}
    for mode in ("BASELINE","MODIFIED","ROLLBACK"):
        certificate = read(mode+"_CERTIFY.json")
        commands = read(mode+"_COMMANDS.json")
        assert certificate["stdout"] == mode+"_PASS cases=10" and certificate["exitStatus"] == 0
        assert len(commands) == 10 and all(c["exitStatus"] == 0 for c in commands)
        report = read(mode+"_SPANS.json")
        assert len(report["rows"]) == 27 and report["originalIATRestored"] and report["liveAliasesVerified"]
        spans[mode] = sum(r["commitBytes"] for r in report["rows"] if r["label"].startswith("over-budget"))
        warm = read(mode+"_WARM.json")
        small[mode] = dict(remaps=warm["coldAcquireRemaps"],milliseconds=warm["allocationMs"])
        certificates.append(certificate)
    assert spans == dict(BASELINE=805306368,MODIFIED=0,ROLLBACK=805306368)
    assert all(r["remaps"] == 10931 for r in small.values())
    paths = {n:str(HERE/f) for n,f in (("MODIFIED_FILE","MODIFIED_FILE.dll"),("DIFF_FILE","DIFF_FILE.patch"),
        ("VERIFICATION","VERIFICATION.txt"),("ROLLBACK","ROLLBACK.sh"))}
    observation = read("BASELINE_READONLY_66908.json")
    assert observation["endpointsEqual"] and observation["runtimeSHA256"] == patch["baselineSHA256"]
    assert observation["state"]["rejected"] == 0 and observation["state"]["sortRuns"] == 127
    result = dict(baselineGameObservation=dict(pid=observation["pid"],sortRuns=127,rejected=0,
        lastPendingPages=observation["state"]["lastPendingPages"],role="diagnostic-not-first-ready"),changedBranch="whole-free merge: independent size decision -> reserve-aware coalescing",
        changedFields="native mixed mapped/cold state; first43 controller words preserved; append8 counters",
        preserved="collector, objects/addresses/content, TLS/locks, blacklist, OOM, native growth, section cap4096, warm64KiB, reserve256MiB",
        baselineSHA256=patch["baselineSHA256"],modifiedSHA256=patch["modifiedSHA256"],paths=paths,
        certification=certificates,overBudgetRepeatedCommitBytes=spans,smallPageRegression=small,
        installed=install,gameBenefitBytes=None,gameCalls=0,gameWrites=0,forcedGameGC=False,
        restoredBehavior="independent copy restores16AAF and the768MiB fixture recommit; candidate remains changed",
        limitation="fixture flow is not peak/resident savings; not an attribution of persistent game growth")
    (HERE/"RESULT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines = ["Changed branch: "+result["changedBranch"],"Changed fields: "+result["changedFields"],
        "Preserved: "+result["preserved"],"BASELINE_SHA256="+patch["baselineSHA256"],"MODIFIED_SHA256="+patch["modifiedSHA256"]]
    lines += [n+"="+p for n,p in paths.items()]
    for c in certificates:
        lines += ["",c["mode"],"cwd="+c["workingDirectory"],"command="+c["command"],
                  "input="+json.dumps(c["input"]),"stdout(literal)="+c["stdout"],"exitStatus="+str(c["exitStatus"])]
    lines += ["","Restored: independent copy hash16AAF and original768MiB repeated recommit behavior; candidate retained.",
        "Ten cases/arm: idle/quick/stress, lifecycle, OOM, fragmented sections, warm pages, >1M pending, faults, 27 VM span cases.",
        "All mixed directions/ties/within-budget/cold-cold spans coalesce; free totals, links, heap sections and VM/native counters close.",
        "Native VirtualAlloc/VirtualFree observation uses only the private helper IAT; original imports restored before managed execution resumes.",
        "Fixture correction: mapped/mapped neighbors normally coalesce inside freehblk, not in the mixed-state merge input.",
        "Over-budget repeated commit bytes: "+json.dumps(spans),"Small-page helper observation: "+json.dumps(small),
        "No stable timing, game resident benefit, or cause of the persistent slope is established.",
        "Budget veto may retain less warm storage than native size-only ordering would eventually choose; first-ready loading must be checked.",
        "Merged extents do not move live objects; no dynamic section table, growth shrink, game GC, WS trim, game start/stop or memory writes.",
        "COLD_INSTALL","command="+command["command"],"input="+json.dumps(command["input"]),
        "stdout(literal):",command["stdout"],"exitStatus=0","installedSHA256="+install["installedSHA256"],
        "81 snapshot members verified; only Mono member changed; application DLL1.5.0 preserved.",
        "Cold restore: powershell -NoProfile -File install.ps1 -Mode Restore (after normal game exit).",
        "Local integration tools reuse adjacent audited build/validation/install modules; this archive is not a standalone source checkout."]
    (HERE/"VERIFICATION.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
    (HERE/"README.md").write_text(
        "# Mono 空闲区段生命周期重构\n\n"
        "已正常退出后冷安装；游戏未自动启动。改造是整块空闲合并与提交储备的一体化决策，不改变GC次数。\n"
        "预算内保留原选择；超预算混合区段直接合并为冷块，避免先补提交再退提交。原扩堆、4096区段、64KiB温区和256MiB储备保持。\n"
        "基线/候选/副本回滚各十组真实Mono测试通过；27个区段用例中的768MiB是避免的累计往返流量，不是游戏驻留收益。\n\n"
        "候选：MODIFIED_FILE.dll；已安装：F:/vam1.22.0.12/Mono/EmbedRuntime/mono.dll。\n"
        "冷恢复16AAF：游戏正常退出后运行 `powershell -NoProfile -File install.ps1 -Mode Restore`。\n"
        "`ROLLBACK.sh`只恢复/测试独立副本，不替换游戏。验证细节及准确命令见VERIFICATION.txt。\n"
        "本包供当前本地工程复用，脚本依赖相邻既有模块；单DLL本身没有新增外部依赖。\n"
        "原算法参考：[Mono allchblk.c](https://raw.githubusercontent.com/mono/mono/mono-2-10/libgc/allchblk.c)，实际ABI以本地DLL审计为准。\n",
        encoding="utf-8")
    package = ROOT/"Mono_Free_Span_Lifecycle_20261006.zip"
    files = ["MODIFIED_FILE.dll","BASELINE.dll","DIFF_FILE.patch","VERIFICATION.txt","ROLLBACK.sh",
        "rollback.py","install.ps1","PATCH.json","RESULT.json","README.md","reclaim_controller.c",
        "build.py","CERTIFY.ps1","validate.py","run_case.py","capture.py","cohort_test.py","isolation_test.py",
        "span_test.py","finalize.py","INSTALL_VERIFIED.json","DEPLOY_COMMAND.json","INSTALL_COPY_COMMANDS.json","BASELINE_READONLY_66908.json"]
    with zipfile.ZipFile(package,"w",compression=zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            info = zipfile.ZipInfo(HERE.name+"/"+name)
            info.create_system = 3
            info.external_attr = (0o100755 if name == "ROLLBACK.sh" else 0o100644)<<16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info,(HERE/name).read_bytes())
    with zipfile.ZipFile(package) as archive:
        assert archive.testzip() is None
        assert hashlib.sha256(archive.read(HERE.name+"/MODIFIED_FILE.dll")).hexdigest() == patch["modifiedSHA256"]
        assert (archive.getinfo(HERE.name+"/ROLLBACK.sh").external_attr>>16)&0o111
    for path in paths.values(): assert Path(path).read_bytes()
    print(f"ARTIFACTS_PASS reopened=4 packageCRC=pass members={len(files)} deployed=True snapshot=81 monoOnly=True")


if __name__ == "__main__":
    main()
