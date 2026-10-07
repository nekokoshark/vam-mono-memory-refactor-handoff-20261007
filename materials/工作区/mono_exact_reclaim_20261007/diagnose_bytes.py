"""Run unchanged modified-arm lifecycle assertions on deployed D4."""
from pathlib import Path
import sys, types
HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent / "mono_interior_commit_lifecycle_20261007"
sys.path.insert(0,str(HERE.parent / "mono_allocator_lifecycle_20261006"))
sys.path.insert(0,str(PRIOR))
s=(PRIOR / "lifecycle_test.py").read_text(encoding="utf-8")


s=s.replace('mode+"_', '"DIAGNOSTIC_BYTES_"+mode+"_')
m=types.ModuleType("baseline_modified_arm")
m.__file__=str(PRIOR / "lifecycle_test.py")
exec(compile(s,m.__file__,"exec"),m.__dict__)
m.HERE=HERE
s=s.replace('values = (C.c_uint64 * len(FIELDS)).from_address(mono._handle + patch["stateRVA"])','values = __import__("struct").unpack("<"+"Q"*len(FIELDS), reader.read(mono._handle + patch["stateRVA"],8*len(FIELDS)))')
m=types.ModuleType("byte_observer")
m.__file__=str(PRIOR / "lifecycle_test.py")
exec(compile(s,m.__file__,"exec"),m.__dict__)
m.HERE=HERE
m.main("MODIFIED")
