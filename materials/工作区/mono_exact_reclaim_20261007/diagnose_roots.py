"""Original helper/GC assertions plus weak/static root telemetry, no game access."""
from pathlib import Path
import sys,types,threading,ctypes as C,subprocess,json
HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent/"mono_interior_commit_lifecycle_20261007"
sys.path.insert(0,str(HERE.parent/"mono_allocator_lifecycle_20261006"))
sys.path.insert(0,str(PRIOR))
arm=sys.argv[1]
control=len(sys.argv)>2 and sys.argv[2] in ("control","hold")
hold=len(sys.argv)>2 and sys.argv[2]=="hold"
s=(PRIOR/"lifecycle_test.py").read_text(encoding="utf-8")
if arm=="D4":
    s=s.replace('"MODIFIED": "MODIFIED_FILE.dll"','"MODIFIED": "BASELINE.dll"')
    s=s.replace('patch["modifiedSHA256" if mode == "MODIFIED" else "baselineSHA256"]','patch["baselineSHA256"]')
s=s.replace('mode+"_', '"ROOT_DIAGNOSTIC_'+arm+("_HOLD" if hold else "_CONTROL" if control else "")+'_"+mode+"_')
s=s.replace('    rows = []','''    rows = []
    probe=C.CDLL(str(HERE/"root_probe.dll"))
    probe.track.argtypes=[ptr,ptr,ptr];probe.track.restype=C.c_uint64
    probe.check.argtypes=[ptr,ptr,ptr];probe.check.restype=C.c_uint
    vt=api("mono_class_vtable",ptr,ptr,ptr)(domain,klass)
    field=api("mono_class_get_field_from_name",ptr,ptr,C.c_char_p)(klass,b"large")
    probe.collect_with_stack_root.argtypes=[ptr,C.c_int];probe.collect_with_stack_root.restype=None
    probe.configure.argtypes=[C.c_uint64];probe.configure.restype=None
    probe.report.argtypes=[C.POINTER(C.c_uint64)];probe.report.restype=None
    kernel=C.WinDLL("kernel32",use_last_error=True)
    kernel.VirtualAlloc.argtypes=[ptr,C.c_size_t,C.c_uint,C.c_uint];kernel.VirtualAlloc.restype=ptr
    kernel.VirtualProtect.argtypes=[ptr,C.c_size_t,C.c_uint,C.POINTER(C.c_uint)];kernel.VirtualProtect.restype=C.c_int
    kernel.FlushInstructionCache.argtypes=[ptr,ptr,C.c_size_t];kernel.FlushInstructionCache.restype=C.c_int
    probe.configure(mono._handle)
    hooksite=mono._handle+0x15a038
    saved_call=C.string_at(hooksite,5)
    assert saved_call==b"\\xe8"+(0x15b240-0x15a03d).to_bytes(4,"little",signed=True)
    thunk=0
    for attempt in range(1,2048):
        thunk=kernel.VirtualAlloc((mono._handle&~65535)+attempt*65536,4096,0x3000,4)
        if thunk:break
    assert thunk and abs(thunk-hooksite)<2**31
    code=b"\\x48\\xb8"+C.cast(probe.record_push,ptr).value.to_bytes(8,"little")+b"\\xff\\xe0"
    C.memmove(thunk,code,len(code));oldprotect=C.c_uint()
    assert kernel.VirtualProtect(thunk,4096,0x20,C.byref(oldprotect))
    assert kernel.FlushInstructionCache(ptr(-1),thunk,len(code))
    assert kernel.VirtualProtect(hooksite,5,0x40,C.byref(oldprotect))
    C.memmove(hooksite,b"\\xe8"+(thunk-hooksite-5).to_bytes(4,"little",signed=True),5)
    restoreprotect=C.c_uint()
    assert kernel.VirtualProtect(hooksite,5,oldprotect.value,C.byref(restoreprotect))
    assert kernel.FlushInstructionCache(ptr(-1),hooksite,5)
    diagnostic=[]
    def off_stack(f,*args):
        result=[];errors=[]
        def run():
            try:result.append(f(*args))
            except BaseException as e:errors.append(e)
        t=observer_threading.Thread(target=run);t.start();t.join()
        if errors:raise errors[0]
        return result[0]
    def scan(stage):
        status=off_stack(probe.check,mono._handle,vt,field)
        diagnostic.append(dict(stage=stage,staticNonNull=bool(status&2),weakAlive=bool(status&1)))
        (HERE/("ROOT_STATUS_"+diagnostic_arm+".json")).write_text(json.dumps(diagnostic,indent=2)+"\\n",encoding="utf-8")
        stats=(C.c_uint64*261)();probe.report(stats)
        captured=list(stats)
        diagnostic[-1]["pushCalls"]=captured[0]
        diagnostic[-1]["stackBytes"]=captured[1]
        diagnostic[-1]["stackMatches"]=captured[2]
        diagnostic[-1]["rejectedRanges"]=captured[3]
        diagnostic[-1]["matches"]=[dict(tid=captured[5+4*i],slotHidden=captured[6+4*i],targetOffset=captured[7+4*i],startHidden=captured[8+4*i]) for i in range(min(64,captured[2]))]
        (HERE/("ROOT_STATUS_"+diagnostic_arm+".json")).write_text(json.dumps(diagnostic,indent=2)+"\\n",encoding="utf-8")
        print("ROOT_STACK_SCAN weakAlive="+str(bool(status&1))+" staticNonNull="+str(bool(status&2))+" stackMatches="+str(captured[2]),flush=True)
''')
s=s.replace('        action("PrepareLarge"); action("DropLarge")','''        action("PrepareLarge")
        hidden=off_stack(probe.track,mono._handle,vt,field)
        probe.configure(mono._handle)
        action("DropLarge")
''')
s=s.replace('        for cycle in range(1, 4): gc("LargeFreeGC" + str(cycle))','''        for cycle in range(1,4):
            gc("LargeFreeGC"+str(cycle))
            scan("GC"+str(cycle))
''')
s=s.replace('        reader.close()', '''        protect=C.c_uint()
        assert kernel.VirtualProtect(hooksite,5,0x40,C.byref(protect))
        C.memmove(hooksite,saved_call,5)
        afterprotect=C.c_uint()
        assert kernel.VirtualProtect(hooksite,5,protect.value,C.byref(afterprotect))
        assert kernel.FlushInstructionCache(ptr(-1),hooksite,5)
        assert C.string_at(hooksite,5)==saved_call
        print("DIAGNOSTIC_HOOK_RESTORED originalCall=True gameTouched=False",flush=True)
        reader.close()''')
s=s.replace('        collect(generation)','''        if diagnostic_control and (stage=="LargeFreeGC1" or diagnostic_hold and stage.startswith("LargeFreeGC")):
            probe.collect_with_stack_root(mono._handle,generation)
        else: collect(generation)''')
m=types.ModuleType("root_diagnostic");m.__file__=str(PRIOR/"lifecycle_test.py")
exec(compile(s,m.__file__,"exec"),m.__dict__)
m.HERE=HERE;m.observer_threading=threading;m.diagnostic_subprocess=subprocess;m.diagnostic_arm=arm+("_HOLD" if hold else "_CONTROL" if control else "");m.diagnostic_control=control;m.diagnostic_hold=hold
m.main("MODIFIED")
