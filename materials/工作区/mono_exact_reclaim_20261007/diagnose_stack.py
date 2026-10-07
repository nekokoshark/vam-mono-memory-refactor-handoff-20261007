"""Run unchanged modified-arm lifecycle assertions on deployed D4."""
import ctypes as C
from pathlib import Path
import sys, types
HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent / "mono_interior_commit_lifecycle_20261007"
sys.path.insert(0,str(HERE.parent / "mono_allocator_lifecycle_20261006"))
sys.path.insert(0,str(PRIOR))
s=(PRIOR / "lifecycle_test.py").read_text(encoding="utf-8")


s=s.replace('mode+"_', '"DIAGNOSTIC_STACK_"+mode+"_')
m=types.ModuleType("baseline_modified_arm")
m.__file__=str(PRIOR / "lifecycle_test.py")
exec(compile(s,m.__file__,"exec"),m.__dict__)
m.HERE=HERE
bridge=C.CDLL(str(HERE / "observer_stack.dll"))
f=bridge.observe_collect
f.restype=None
f.argtypes=[C.c_void_p,C.c_int]
s=s.replace('        collect(generation)','        observer_bridge(C.cast(collect,C.c_void_p),generation)')
m=types.ModuleType("stack_neutral_observer")
m.__file__=str(PRIOR / "lifecycle_test.py")
exec(compile(s,m.__file__,"exec"),m.__dict__)
m.HERE=HERE
m.observer_bridge=f
m.main(sys.argv[1] if len(sys.argv)>1 else "MODIFIED")
