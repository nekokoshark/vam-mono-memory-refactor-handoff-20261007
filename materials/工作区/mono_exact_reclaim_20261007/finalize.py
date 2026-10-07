"""Reopen candidate/evidence and package a non-approved local research build."""
from __future__ import annotations
import hashlib, json, zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> None:
    patch=json.loads((HERE/"PATCH.json").read_text(encoding="utf-8"))
    assert digest(HERE/"BASELINE.dll")==patch["baselineSHA256"]
    assert digest(HERE/"MODIFIED_FILE.dll")==patch["modifiedSHA256"]
    assert digest(HERE/"rollback_copy/mono.dll")==patch["baselineSHA256"]
    assert digest(ROOT/"Mono/EmbedRuntime/mono.dll")==patch["baselineSHA256"]
    assert not json.loads((HERE/"RELEASE_GATE.json").read_text(encoding="utf-8"))["approved"]
    paths={name:str(HERE/name) for name in ("MODIFIED_FILE.dll","DIFF_FILE.patch","VERIFICATION.txt","ROLLBACK.sh")}
    lines=["STATUS: CANDIDATE_ONLY / NOT_APPROVED / NOT_DEPLOYED",
        "Changed branch: order_reclaim: eight coarse density bands -> stable descending exact marked-object count (513 bins).",
        "Original 94 words preserved; 3 counters + 1026 complemented non-owning scratch words added, cleared before publishing.",
        "Seven hooks preserved; original marking, locks, addresses, contents, blacklist, growth and 4096 section cap preserved.",
        "BASELINE_SHA256="+patch["baselineSHA256"],"MODIFIED_SHA256="+patch["modifiedSHA256"]]
    lines.extend(name+"="+path for name,path in paths.items())
    for arm in ("BASELINE","MODIFIED","ROLLBACK"):
        cert=json.loads((HERE/(arm+"_CERTIFY.json")).read_text(encoding="utf-8-sig"))
        records=json.loads((HERE/(arm+"_COMMANDS.json")).read_text(encoding="utf-8"))
        assert cert["exitStatus"]==0 and len(records)==14 and all(r["exitStatus"]==0 for r in records)
        assert cert["stdout"]==arm+"_PASS cases=14"
        lines += ["",arm+" exact command: "+cert["command"],"Working directory: "+str(HERE),
            "Input: "+json.dumps(cert["input"],ensure_ascii=False),"Literal stdout: "+cert["stdout"],"Exit status: 0",
            "Nested exact commands/input/literal output/status: "+str(HERE/(arm+"_COMMANDS.json")),cert["nestedOutput"]]
    b=json.loads((HERE/"BASELINE_EXACT.json").read_text(encoding="utf-8"))
    m=json.loads((HERE/"MODIFIED_EXACT.json").read_text(encoding="utf-8"))
    r=json.loads((HERE/"ROLLBACK_EXACT.json").read_text(encoding="utf-8"))
    assert b["rows"][0]["exactInversions"]==14 and m["rows"][0]["exactInversions"]==0 and r["rows"][0]["exactInversions"]==14
    lines += ["", "Restored behavior/status: independent-copy D4685C71 hash restored; original coarse ordering exact inversions 14 -> 0 -> 14; all 14 rollback cases passed. Candidate remains modified.",
        "Important failures: two original candidate runs retained the released 768MiB payload and failed unchanged avoided > 64MiB assertion (AssertionError: 0, exit 1); first evidence retained in INITIAL_MODIFIED_LARGE_RETAINED_*.",
        "Diagnostic D4 baseline under modified-arm assertions failed the same assertion; byte-copy/observer-thread experiments were not consistently passing. Cause remains unresolved. No success retry authorizes installation.",
        "Latest complete three-arm pass is algorithm/protocol evidence, not stable large-object retirement proof, game RAM savings or explanation of 2%-3% per-round growth.",
        "Live sampling: 3203 pages, 611 adjacent same-band exact-count inversions, 0.438s, partial accepted chains only; not a global atomic/root/heap attribution.",
        "Production Mono remains D4685C71; VaM.Memory remains 1.5.0 / 300d8335a2faedd473a09a0cb27c28df519413ffadf6c4e555f6a3b673278da8. No process was stopped or started.",
        "Root follow-up: CAPTURED_STALE_ROOT_FAILURE.json records actual GC2/GC3 main-stack residual roots after an explicit control slot ended; static=null, weak=alive, original AssertionError:0 exit1. Controlled evidence only; earlier uninstrumented incident remains unattributed.",
        "INSTALL gate=false. Next required work: explain original native lifecycle retention with root/worker-exit evidence before releasing this candidate."]
    (HERE/"VERIFICATION.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
    (HERE/"README.md").write_text("""# Mono exact-reclaim candidate — 未批准部署

待清扫队列按同 kind/size 的实际标记对象数稳定降序排列，替代八档密度；不搬对象，不改原标记器、清扫器、锁、扩堆或区段上限。

最新基线/候选/独立回滚各14项通过，排序夹具同档逆序14→0→14；但此前两次768MiB释放失败，基线改用同样观测也出现失败，观测路径调整未稳定解决。原因尚未确认，安装门槛保持关闭，成功重试不覆盖失败证据。

生产仍为D4685C71。本目录及根目录ZIP是开发候选与真实证据，不是本次游戏收益或可安装发行版。四产物、原方法精确命令和退出状态见VERIFICATION.txt；继续处理大对象生命周期不稳定后再批准冷替换。
""",encoding="utf-8")
    for name,path in paths.items():
        raw=Path(path).read_bytes()
        assert raw
        if name!="MODIFIED_FILE.dll": raw.decode("utf-8")
    archive=ROOT/"Mono_Exact_Reclaim_Candidate_20261007.zip"
    excluded={"BASELINE.dll","LifecycleSample.dll","RetireSample.dll","PendingCohort.dll","WarmPages.dll","pending_probe.dll","observer_stack.dll","observer_stack.obj","observer_stack.lib","observer_stack.exp","test_reuse.py","root_probe.obj","root_probe.lib","root_probe.exp"}
    members=[f for f in HERE.iterdir() if f.is_file() and f.name not in excluded]
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
        for f in members: z.write(f,"mono_exact_reclaim_20261007/"+f.name)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for f in members:
            assert z.read("mono_exact_reclaim_20261007/"+f.name)==f.read_bytes()
    print("ARTIFACTS_REOPENED paths=4 candidate=427AAB71 baseline+rollback=D4685C71 releaseApproved=False productionChanged=False")
    print("PACKAGE_PASS CRC=verified members="+str(len(members))+" path="+str(archive))

if __name__=="__main__": main()
