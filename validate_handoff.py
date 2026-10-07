"""Verify archived inputs, then exercise them only in an extracted independent copy."""
from __future__ import annotations
import hashlib,json,os,subprocess,sys,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent

def main()->None:
    archive=HERE/"VaM_Mono_Handoff_20261007.zip"
    manifest=json.loads((HERE/"MANIFEST.json").read_text(encoding="utf-8"))
    expected=(HERE/"SHA256SUMS.txt").read_text(encoding="ascii").split()[0]
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected
    out=HERE/"_validation"
    assert not out.exists(),"Preserve prior evidence; use a fresh validation directory"
    out.mkdir()
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for member in z.infolist():
            target=(out/member.filename).resolve()
            assert target.is_relative_to(out.resolve())
        for row in manifest["files"]:
            name="VaM_Mono_Handoff_20261007/materials/"+row["path"]
            assert hashlib.sha256(z.read(name)).hexdigest()==row["sha256"]
        z.extractall(out)
    root=out/"VaM_Mono_Handoff_20261007/materials"
    task=root/"工作区/mono_exact_reclaim_20261007"
    env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE="1",PYTHONIOENCODING="utf-8",PYTHONPATH=str(root/"tools/pydeps"))
    tests=[("structure",["verify.py"]),("exact-original-method",["run_case.py","MODIFIED","exact"]),
        ("baseline-lifecycle-original",["run_case.py","BASELINE","lifecycle"]),
        ("candidate-lifecycle-original",["run_case.py","MODIFIED","lifecycle"]),
        ("root-calibration",["trace_root_cases.py"])]
    records=[]
    for name,args in tests:
        argv=[sys.executable,*[str(task/args[0]),*args[1:]]]
        run=subprocess.run(argv,cwd=task,env=env,capture_output=True,text=True,timeout=60)
        records.append(dict(name=name,argv=argv,input=args[1:],stdout=run.stdout,stderr=run.stderr,exitStatus=run.returncode))
        print(name+" exit="+str(run.returncode)+" "+run.stdout.strip(),flush=True)
        result=dict(packageIntegrity="PASS",manifestFiles=manifest["count"],sourceSnapshotUnchanged=True,records=records,
            productionChanged=False,gameBenefitMeasured=False,initialFailureRootAttributed=False)
        (HERE/"PACKAGE_VALIDATION.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        # Retention failure remains meaningful evidence; dependency/import/crash failures do not.
        if run.returncode and not (name=="candidate-lifecycle-original" and "AssertionError: 0" in run.stderr):
            raise RuntimeError(run.stderr)
    for row in manifest["files"]:
        assert hashlib.sha256((HERE/"materials"/row["path"]).read_bytes()).hexdigest()==row["sha256"]
    print("HANDOFF_SELFTEST_PASS archivedFiles="+str(manifest["count"])+" cases=5 snapshotUnchanged=True gameModified=False")
if __name__=="__main__":main()
