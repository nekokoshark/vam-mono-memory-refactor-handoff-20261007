"""Cross-over diagnostic: same lifecycle assertions, short-lived read-only observer stack."""
from pathlib import Path
import sys, types, threading
HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent / "mono_interior_commit_lifecycle_20261007"
sys.path.insert(0,str(HERE.parent / "mono_allocator_lifecycle_20261006"))
sys.path.insert(0,str(PRIOR))
s=(PRIOR / "lifecycle_test.py").read_text(encoding="utf-8")
arm=sys.argv[1]
if arm=="D4":
    s=s.replace('"MODIFIED": "MODIFIED_FILE.dll"','"MODIFIED": "BASELINE.dll"')
    s=s.replace('patch["modifiedSHA256" if mode == "MODIFIED" else "baselineSHA256"]','patch["baselineSHA256"]')
s=s.replace('mode+"_', '"DIAGNOSTIC_THREAD_'+arm+'_"+mode+"_')
s=s.replace('    def snapshot(stage:', '    def original_snapshot(stage:')
s=s.replace('    def action(name:', '''    def observe(function, *args):
        outputs, errors = [], []
        def run():
            try: outputs.append(function(*args))
            except BaseException as error: errors.append(error)
        worker=observer_threading.Thread(target=run)
        worker.start(); worker.join()
        if errors: raise errors[0]
        return outputs[0]

    def snapshot(*args):
        observe(original_snapshot,*args)

    def action(name:''')
s=s.replace('        order = pending_order()', '        order = observe(pending_order)')
m=types.ModuleType("thread_observer")
m.__file__=str(PRIOR / "lifecycle_test.py")
exec(compile(s,m.__file__,"exec"),m.__dict__)
m.HERE=HERE
m.observer_threading=threading
m.main("MODIFIED")
