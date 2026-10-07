"""Build a bounded, self-contained Mono handoff from explicit material roots."""
from __future__ import annotations
import hashlib,json,re,shutil,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
WORK=HERE.parent
GAME=WORK.parent
MATERIALS=HERE/"materials"
CORE=["mono_exact_reclaim_20261007","mono_reuse_lifecycle_20261007","mono_interior_commit_lifecycle_20261007",
    "mono_allocator_lifecycle_20261006","mono_warm_pages_20261006","mono_free_span_lifecycle_20261006",
    "mono_reclaim_cohorts_20261006","mono_reclaim_controller_20261006","mono_unmap_20260930"]
TEXT={".py",".c",".cs",".h",".json",".txt",".md",".patch",".ps1",".sh"}
NATIVE_DIRS={"mono_exact_reclaim_20261007","mono_reuse_lifecycle_20261007","mono_allocator_lifecycle_20261006"}
FILES=[]

def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()

def copy(source:Path,relative:Path)->None:
    assert source.is_file(),source
    target=MATERIALS/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():assert source.read_bytes()==target.read_bytes(),target
    shutil.copy2(source,target)
    assert source.read_bytes()==target.read_bytes()
    FILES.append(dict(path=relative.as_posix(),bytes=target.stat().st_size,sha256=sha(target)))

def main()->None:
    assert not (HERE/"MANIFEST.json").exists(),"Preserve the completed snapshot"
    for folder in CORE:
        for f in sorted((WORK/folder).iterdir()):
            if not f.is_file():continue
            if f.suffix.lower() in TEXT:
                copy(f,Path("工作区")/folder/f.name)
            elif f.suffix.lower()==".dll":
                if f.name not in ("BASELINE.dll","MODIFIED_FILE.dll","REJECTED.dll") or folder in NATIVE_DIRS:
                    copy(f,Path("工作区")/folder/f.name)
    for name in ("MODIFIED_FILE.py","PAIR_RESULT.json","FINDINGS.md","START_01.json","RETURN_01.json"):
        copy(WORK/"allocator_growth_pair_20261006"/name,Path("工作区/allocator_growth_pair_20261006")/name)
    for name in ("mscorlib.dll","System.dll","System.Core.dll"):
        copy(GAME/"VaM_Data/Managed"/name,Path("VaM_Data/Managed")/name)
    copy(GAME/"Mono/EmbedRuntime/mono.dll",Path("Mono/EmbedRuntime/mono.dll"))
    copy(GAME/"BepInEx/plugins/VaMMemory/VaM.Memory.dll",Path("BepInEx/plugins/VaMMemory/VaM.Memory.dll"))
    copy(GAME/"BepInEx/config/vam.memory.cfg",Path("BepInEx/config/vam.memory.cfg"))
    for f in sorted((GAME/"Mono/etc").rglob("*")):
        if f.is_file():copy(f,f.relative_to(GAME))
    deps=GAME/"tools/pydeps"
    for f in sorted(deps.rglob("*")):
        if not f.is_file() or "__pycache__" in f.parts or f.suffix in (".pyc",".pyo"):continue
        copy(f,Path("tools/pydeps")/f.relative_to(deps))
    modules=WORK/"Quest3TriggerUI工程/memory_modules.txt"
    copy(modules,Path("deployed_source/memory_modules.txt"))
    for line in modules.read_text(encoding="utf-8").splitlines():
        name=line.strip()
        if name and not name.startswith("#"):
            copy(WORK/"Quest3TriggerUI工程/plugin_sources"/name,Path("deployed_source/plugin_sources")/name)
    mono=sha(GAME/"Mono/EmbedRuntime/mono.dll")
    memory=sha(GAME/"BepInEx/plugins/VaMMemory/VaM.Memory.dll")
    candidate=sha(MATERIALS/"工作区/mono_exact_reclaim_20261007/MODIFIED_FILE.dll")
    assert mono=="d4685c71704ef7f222feebfb93851d7f3b6d354998c2e6bc8347268e047c7b3d"
    assert memory=="300d8335a2faedd473a09a0cb27c28df519413ffadf6c4e555f6a3b673278da8"
    assert candidate=="427aab71b5b751507ee8165869baeee6ca2a021c852691a942bc971967a1ce35"
    forbidden=re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")
    for row in FILES:
        f=MATERIALS/row["path"]
        if f.suffix.lower() in TEXT or f.suffix.lower()==".cfg":assert not forbidden.search(f.read_bytes()),f
    index=dict(date="2026-10-07",repository="nekokoshark/vam-mono-memory-refactor-handoff-20261007",
        visibility="private",productionMonoSHA256=mono,productionVaMMemorySHA256=memory,candidateMonoSHA256=candidate,
        candidateApproved=False,productionChanged=False,sourceDirectories=CORE+["allocator_growth_pair_20261006"],
        entry="PROMPT.md",originalFailure="materials/工作区/mono_exact_reclaim_20261007/INITIAL_MODIFIED_LARGE_RETAINED_TRACE.json",
        capturedControlledFailure="materials/工作区/mono_exact_reclaim_20261007/CAPTURED_STALE_ROOT_FAILURE.json",
        nativeFixture="materials/工作区/mono_allocator_lifecycle_20261006/LifecycleSample.cs",
        nativeAssertions="materials/工作区/mono_interior_commit_lifecycle_20261007/lifecycle_test.py",
        requirements=["Windows x64","64-bit Python","MSVC 14.44.35207 for rebuilding","csc against supplied mscorlib for rebuilding helpers"],
        missingEnvironment=["Python interpreter installation","MSVC/Windows SDK installation"],
        contextOnly="VaM.Memory deployed DLL/config + memory_modules source snapshot; not a claim of a complete standalone VaM.Memory rebuild kit",
        noGameFilesChanged=True)
    (HERE/"HANDOFF_INDEX.json").write_text(json.dumps(index,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (HERE/"MANIFEST.json").write_text(json.dumps(dict(files=FILES,count=len(FILES),totalBytes=sum(f["bytes"] for f in FILES)),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    archive=GAME/"VaM_Mono_Handoff_20261007.zip"
    docs=["README.md","PROMPT.md","HANDOFF_INDEX.json","MANIFEST.json","QUICKSTART.ps1","pack.py"]
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name in docs:z.write(HERE/name,"VaM_Mono_Handoff_20261007/"+name)
        for row in FILES:z.write(MATERIALS/row["path"],"VaM_Mono_Handoff_20261007/materials/"+row["path"])
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for row in FILES:assert hashlib.sha256(z.read("VaM_Mono_Handoff_20261007/materials/"+row["path"])).hexdigest()==row["sha256"]
        for name in docs:assert z.read("VaM_Mono_Handoff_20261007/"+name)==(HERE/name).read_bytes()
    shutil.copy2(archive,HERE/archive.name)
    (HERE/"SHA256SUMS.txt").write_text(sha(archive)+"  "+archive.name+"\n",encoding="ascii")
    # Binary references, native dependencies and Mono config stay in the ZIP.
    (HERE/".gitignore").write_text("*.dll\n*.exe\n*.pyd\n*.obj\n*.lib\n*.exp\n__pycache__/\n_validation/\nisolated-run-*/\nmaterials/Mono/\nmaterials/VaM_Data/\nmaterials/tools/\n",encoding="utf-8")
    print("HANDOFF_PACKAGE_PASS files="+str(len(FILES))+" rawBytes="+str(sum(f["bytes"] for f in FILES))+" zipBytes="+str(archive.stat().st_size)+" CRC=verified SHA256="+sha(archive))
    print("PRODUCTION_HASH_PASS mono=D4685C71 memory=300D8335 candidate=427AAB71 candidateApproved=False")
if __name__=="__main__":main()
