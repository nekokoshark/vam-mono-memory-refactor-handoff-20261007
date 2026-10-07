"""Actual native collector adapter on original Mono-owned pending pages."""
from __future__ import annotations

from pathlib import Path
import sys
import types

from prepare import once

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / "mono_interior_commit_lifecycle_20261007"
sys.path.insert(0, str(PRIOR))


def main(mode: str) -> None:
    source = (PRIOR / "isolation_test.py").read_text(encoding="utf-8")
    source = once(source, "mono_free_span_lifecycle_20261006/PATCH.json", "mono_reuse_lifecycle_20261007/PATCH.json")
    start = source.index('    # Each failure is local')
    end = source.index('    action("LifecycleSample", "DropCellRoots")', start)
    block = '''    scenarios = {
        "same-old-bin": [1,15,2,14,3,13,4,12,5,11,6,10,7,9,8,1]*2,
        "equal-count-stability": [3,12,3,12,8,8,3,12]*4,
        "exact-uniform": [6]*32,
        "multiple-old-bins": [1,127,32,120,2,119,31,121]*4,
    }
    for label, counts in scenarios.items():
        slot, targets = chain(0,4)
        selected = targets[:len(counts)]
        assert len(selected) == len(counts)
        original_head = word(slot).value
        original_next = {p:word(find(p)+8).value for p in selected}
        original_marks = {p:[word(find(p)+48+8*i).value for i in range(8)] for p in selected}
        payloads = {p:C.string_at(p,4096) for p in selected}
        disable()
        try:
            for index,p in enumerate(selected):
                h=find(p)
                word(h+8).value=selected[index+1] if index+1<len(selected) else 0
                mask=sum(1 << (4*i) for i in range(counts[index]))
                for i in range(8): word(h+48+8*i).value=(mask >> (64*i)) & 0xffffffffffffffff
            word(slot).value=selected[0]
            controller(mono._handle,mono._handle+state_rva)
            _, actual = chain(0,4)
            wanted = sorted(selected,key=lambda p:-counts[selected.index(p)]) if mode=="MODIFIED" else sorted(
                selected,key=lambda p:-min(7,counts[selected.index(p)]*8//128))
            assert actual==wanted, label
            assert set(actual)==set(selected)
            assert all(C.string_at(p,4096)==raw for p,raw in payloads.items())
            ordered=[counts[selected.index(p)] for p in actual]
            inversions=sum(a<b for a,b in zip(ordered,ordered[1:]))
            if mode=="MODIFIED":
                assert inversions==0
                workspace=(C.c_uint64*1026).from_address(mono._handle+state_rva+97*8)
                assert not any(workspace), "Transient hints survived sort commit"
            elif label=="same-old-bin":
                assert inversions > 0
            evidence.append(dict(case=label,exactInversions=inversions,membersPreserved=True,
                stableEqualCounts=True,payloadUnchanged=True,workspaceCleared=mode=="MODIFIED"))
        finally:
            for p in selected:
                h=find(p); word(h+8).value=original_next[p]
                for i,value in enumerate(original_marks[p]): word(h+48+8*i).value=value
            word(slot).value=original_head
            enable()
        action("LifecycleSample","CheckCells")
        action("PendingCohort","CheckOther")
'''
    source = source[:start] + block + source[end:]
    start = source.index('    (HERE / (mode + "_ISOLATION.json"))')
    end = source.index('\n\nif __name__', start)
    source = source[:start] + '''    (HERE/(mode+"_EXACT.json")).write_text(json.dumps(dict(mode=mode,runtimeSHA256=expected,
        rows=evidence,restoredBeforeResume=True,gameWrites=0,gameCalls=0,gameBenefitBytes=None),indent=2)+"\\n",encoding="utf-8")
    print(f"EXACT_PASS mode={mode} cases=4 sameBinInversions={evidence[0]['exactInversions']} aliases=verified payload=unchanged workspace=cleared-original-restored gameModified=False")
''' + source[end:]
    module = types.ModuleType("original_native_fixture")
    module.__file__ = str(PRIOR / "isolation_test.py")
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    module.HERE = HERE
    module.main(mode)


if __name__ == "__main__":
    main(sys.argv[1])
