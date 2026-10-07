"""Bounded cross-runtime rooted/unrooted controls; failures are kept, not waived."""
from __future__ import annotations
import subprocess,sys,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
records=[]
for arm in ("D4","EXACT"):
    for kind in ("natural","control","hold"):
        command=[sys.executable,str(HERE/"diagnose_roots.py"),arm]+([] if kind=="natural" else [kind])
        result=subprocess.run(command,cwd=HERE,capture_output=True,text=True,timeout=30)
        name=arm+("_HOLD" if kind=="hold" else "_CONTROL" if kind=="control" else "")
        status=json.loads((HERE/("ROOT_STATUS_"+name+".json")).read_text(encoding="utf-8"))
        row=dict(command=command,input=dict(runtime=arm,rootControl=kind,originalGCs=3),stdout=result.stdout,
            stderr=result.stderr,exitStatus=result.returncode,rootStatus=status)
        records.append(row)
        (HERE/"ROOT_CASES.json").write_text(json.dumps(records,indent=2)+"\n",encoding="utf-8")
        print(arm+" "+kind+" exit="+str(result.returncode)+" weakAlive="+str([r["weakAlive"] for r in status])+" roots="+str([r["stackMatches"] for r in status]),flush=True)
        assert "DIAGNOSTIC_HOOK_RESTORED originalCall=True gameTouched=False" in result.stdout
        if kind=="hold":
            assert result.returncode!=0 and "AssertionError: 0" in result.stderr
            assert all(r["weakAlive"] and r["stackMatches"]>=1 and not r["staticNonNull"] for r in status)
        elif kind=="control":
            assert status[0]["weakAlive"] and status[0]["stackMatches"]>=1
            # Ending the explicit slot does not prove every conservative copy
            # is gone. A remaining target must have an actual scanned stack word.
            assert all(not r["weakAlive"] or r["stackMatches"]>=1 for r in status[1:])
            if result.returncode:
                assert "AssertionError: 0" in result.stderr and status[-1]["weakAlive"]
        # Natural outcomes are evidence, not an assumed PASS gate.
print("ROOT_TRACE_CALIBRATION_PASS runtimes=2 cases=6 originalGCs=3 hooksRestored=True gameModified=False")
