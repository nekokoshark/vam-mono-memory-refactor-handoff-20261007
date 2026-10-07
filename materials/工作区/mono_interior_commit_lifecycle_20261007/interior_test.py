"""Original allocator + controlled blacklists + real Windows commitment in a child."""
from __future__ import annotations

import ctypes as C
import hashlib
import json
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = HERE.parent / "mono_free_span_lifecycle_20261006"
MIB = 1024**2
VM_CAPTURE = runpy.run_path(str(HERE.parent / "mono_allocator_lifecycle_20261006/test_vm.py"))["capture"]


class Region(C.Structure):
    _fields_ = [("base", C.c_void_p), ("allocation", C.c_void_p),
                ("allocationProtect", C.c_uint32), ("partition", C.c_uint16),
                ("bytes", C.c_size_t), ("state", C.c_uint32),
                ("protect", C.c_uint32), ("type", C.c_uint32)]


def main(mode: str) -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    old = json.loads((PREVIOUS / "PATCH.json").read_text(encoding="utf-8"))
    path = HERE / {"BASELINE": "BASELINE.dll", "MODIFIED": "MODIFIED_FILE.dll",
                   "ROLLBACK": "rollback_copy/mono.dll"}[mode]
    expected = patch["modifiedSHA256" if mode == "MODIFIED" else "baselineSHA256"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    mono = C.CDLL(str(path))
    base = mono._handle
    ptr, u64 = C.c_void_p, C.c_uint64

    def native(rva: int, result, *args):
        return C.CFUNCTYPE(result, *args)(base + rva)

    def api(name: str, result, *args):
        f = getattr(mono, name)
        f.restype, f.argtypes = result, list(args)
        return f

    api("mono_set_assemblies_path", None, C.c_char_p)((str(HERE) + ";" + str(ROOT / "VaM_Data/Managed")).encode())
    api("mono_set_dirs", None, C.c_char_p, C.c_char_p)(str(ROOT / "VaM_Data/Managed").encode(), str(ROOT / "Mono/etc").encode())
    domain = api("mono_jit_init_version", ptr, C.c_char_p, C.c_char_p)(b"InteriorCommit", b"v2.0.50727")
    assert domain
    assembly = api("mono_domain_assembly_open", ptr, ptr, C.c_char_p)(domain, str(HERE / "LifecycleSample.dll").encode())
    image = api("mono_assembly_get_image", ptr, ptr)(assembly)
    klass = api("mono_class_from_name", ptr, ptr, C.c_char_p, C.c_char_p)(image, b"", b"LifecycleSample")
    method = api("mono_class_get_method_from_name", ptr, ptr, C.c_char_p, C.c_int)
    invoke = api("mono_runtime_invoke", ptr, ptr, ptr, ptr, C.POINTER(ptr))

    def action(name: str) -> None:
        error = ptr()
        assert invoke(method(klass, name.encode(), 0), None, None, C.byref(error)) and not error.value

    action("PrepareCells")
    find = native(0x15ee50, ptr, u64)
    expand = native(0x1580e8, C.c_int, u64)
    allocate = native(0x160004, ptr, u64, C.c_int, C.c_ubyte, C.c_int)
    release = native(0x16044c, None, u64)
    remove = native(0x15fa24, None, ptr, C.c_int)
    add = native(0x15fc04, None, u64, ptr)
    remap = native(0x15ec50, None, u64, u64)
    disable, enable = native(0x158eb8, None), native(0x158e8c, None)
    runtime = patch if mode == "MODIFIED" else old
    controller = native(runtime["exports"]["reclaim_controller"], None, ptr, ptr)
    state = base + runtime["stateRVA"]

    def word(address: int):
        return u64.from_address(address)

    def flags(header: int):
        return C.c_ubyte.from_address(header + 41)

    lists = (u64 * 61).from_address(base + 0x269d70)
    marker = word(base + 0x269f70).value

    def inventory() -> dict[int, tuple[int, int]]:
        found = {}
        for bucket in range(61):
            block, previous = lists[bucket], 0
            while block:
                h = find(block)
                assert h and h > 4096 and block not in found
                size = word(h).value
                assert word(h + 32).value == marker and size and not size % 4096
                assert word(h + 16).value == previous
                found[block] = (h, size)
                previous, block = block, word(h + 8).value
        assert sum(s for _, s in found.values()) == word(base + 0x27c808).value
        return found

    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.VirtualProtect.argtypes = (ptr, C.c_size_t, C.c_uint32, C.POINTER(C.c_uint32))
    kernel.VirtualProtect.restype = C.c_int
    kernel.VirtualQuery.argtypes, kernel.VirtualQuery.restype = (ptr, C.POINTER(Region), C.c_size_t), C.c_size_t
    kernel.FlushInstructionCache.argtypes, kernel.FlushInstructionCache.restype = (ptr, ptr, C.c_size_t), C.c_int
    alloc_type = C.WINFUNCTYPE(ptr, ptr, C.c_size_t, C.c_uint32, C.c_uint32)
    free_type = C.WINFUNCTYPE(C.c_int, ptr, C.c_size_t, C.c_uint32)
    alloc_slot, free_slot = base + 0x1901d8, base + 0x1901e0
    old_alloc, old_free = word(alloc_slot).value, word(free_slot).value
    real_alloc, real_free = alloc_type(old_alloc), free_type(old_free)
    events = []

    @alloc_type
    def observed_alloc(address, size, kind, protect):
        result = real_alloc(address, size, kind, protect)
        events.append(dict(op="commit", address=address, bytes=size, flags=kind, success=bool(result)))
        return result

    @free_type
    def observed_free(address, size, kind):
        result = real_free(address, size, kind)
        events.append(dict(op="decommit", address=address, bytes=size, flags=kind, success=bool(result)))
        return result

    def write(address: int, raw: bytes, executable: bool = False) -> None:
        protection = C.c_uint32()
        assert kernel.VirtualProtect(address, len(raw), 0x40 if executable else 4, C.byref(protection))
        C.memmove(address, raw, len(raw))
        ignored = C.c_uint32()
        assert kernel.VirtualProtect(address, len(raw), protection.value, C.byref(ignored))
        if executable: assert kernel.FlushInstructionCache(ptr(-1), address, len(raw))

    def storage(block: int, size: int) -> dict:
        cursor, committed = block, 0
        while cursor < block + size:
            region = Region()
            assert kernel.VirtualQuery(cursor, C.byref(region), C.sizeof(region)) == C.sizeof(region)
            end = min(region.base + region.bytes, block + size)
            assert end > cursor and region.state in (0x1000, 0x2000)
            if region.state == 0x1000: committed += end - cursor
            cursor = end
        return dict(committed=committed, reserved=size-committed)

    bitmaps = {word(base+rva).value for rva in (0x26c448, 0x26c450, 0x26c458, 0x26c460)}
    assert all(p > 4096 for p in bitmaps)
    saved = {p: C.string_at(p, 131072) for p in bitmaps}
    stack = word(base + 0x26c458).value
    install_bytes = C.string_at(base + 0x15f12c, 3)
    rows = []
    disable()
    reserve, magic = word(state+8).value, word(state).value
    parked = []
    try:
        assert expand(512 * MIB // 4096)
        block, (h, total) = max(inventory().items(), key=lambda pair: pair[1][1])
        assert total >= 512 * MIB and total < 1024 * MIB
        # Isolate the long-bucket fixture through original list operations.
        # Native nth otherwise prefers a smaller eligible next extent.
        other = lists[60]
        while other:
            oh = find(other)
            following = word(oh+8).value
            if other != block:
                size = word(oh).value
                remove(oh,60)
                parked.append((other,oh,size))
                word(base+0x27c808).value -= size
            other = following
        heap, sections, free_total = (word(base+rva).value for rva in (0x27c7e0, 0x269bc8, 0x27c808))
        word(state+8).value = 0
        controller(base, state)
        write(alloc_slot, bytes(u64(C.cast(observed_alloc, ptr).value)))
        write(free_slot, bytes(u64(C.cast(observed_free, ptr).value)))
        cases = [("cold-small",4096,1,True,1,False,False),
                 ("cold-large",2*MIB,2,True,1,False,False),
                 ("cold-nine-pages",65536,9,True,1,False,False),
                 ("cold-exact-right",total-4096,1,True,1,False,False),
                 ("mapped-interior",65536,2,False,1,False,False),
                 ("cold-noninterior",4096,0,True,1,False,False),
                 ("atomic-blacklist-bypass",4096,1,True,0,False,False),
                 ("original-header-failure",4096,1,True,1,True,False),
                 ("invalid-context-fallback",4096,1,True,1,False,True)]
        interior_before = [word(state+i*8).value for i in range(51,56)] if mode == "MODIFIED" else None
        for cycle in range(3):
            for label, need, lead, cold, kind, fail, fallback in cases:
                controller(base,state)
                h = find(block)
                assert inventory()[block][1] == total and flags(h).value & 2
                if not cold:
                    remap(block,total)
                    flags(h).value &= ~2
                remove(h,-1)
                add(block,h)
                assert lists[60] == block
                for p in bitmaps: C.memset(p,0,131072)
                for i in range(lead):
                    bit = ((block//4096)+i)&0xfffff
                    word(stack+8*(bit//64)).value |= 1 << (bit%64)
                if fail: write(base+0x15f12c,bytes.fromhex("31c0c3"),True)
                if fallback: word(state).value = 0
                before = storage(block,total)
                events.clear()
                taken = allocate(need//8,kind,0,60)
                word(state).value = magic
                if fail: write(base+0x15f12c,install_bytes,True)
                accepted_lead = 0 if kind == 0 or fail else lead
                assert taken == (None if fail else block + accepted_lead*4096), (label,taken,block)
                calls = [e for e in events if e["address"] and block <= e["address"] < block+total]
                commits = sum(e["bytes"] for e in calls if e["op"] == "commit")
                after = storage(block,total)
                interior = cold and accepted_lead > 0
                prefix = min(total-accepted_lead*4096,max(65536,need)) if need < 65536 else need
                wanted = total if interior and (mode != "MODIFIED" or fallback) else prefix
                if not cold: wanted = 0
                if fail: wanted = total
                assert commits == wanted and after["committed"]-before["committed"] == commits, (label,calls,before,after,wanted)
                assert all(e["success"] for e in events)
                if fail:
                    # Native FirstPart removes the free header before its failed
                    # tail-header allocation. Restore this private fixture only.
                    assert word(h).value == total and not flags(h).value & 2
                    add(block,h)
                    assert word(base+0x27c808).value == free_total
                    rows.append(dict(cycle=cycle,label=label,need=need,leadBytes=0,total=total,
                                     commitBytes=commits,before=before,after=after,VMcalls=calls,
                                     originalNullResult=True,fixtureListRestored=True))
                    for p,raw in saved.items(): C.memmove(p,raw,len(raw))
                    controller(base,state)
                    inventory()
                    continue
                free = inventory()
                assert sum(s for _,s in free.values()) == free_total-need
                if accepted_lead:
                    assert free[block][1] == accepted_lead*4096
                    assert bool(flags(free[block][0]).value & 2) == (mode == "MODIFIED" and cold and not fallback)
                # Read/write only the actual allocation, including its last page.
                for offset in (0,need//2,need-8):
                    word(taken+offset).value = 0x1234567800000000+offset
                    assert word(taken+offset).value == 0x1234567800000000+offset
                vm = VM_CAPTURE(base)
                assert vm["monoReservedBytes"] == word(base+0x27ea88).value
                assert word(base+0x27c7e0).value == heap and word(base+0x269bc8).value == sections
                assert not any(word(state+i*8).value for i in (26,27,28))
                rows.append(dict(cycle=cycle,label=label,need=need,leadBytes=accepted_lead*4096,total=total,
                                 commitBytes=commits,before=before,after=after,VMcalls=calls,globalVM=vm))
                for p,raw in saved.items(): C.memmove(p,raw,len(raw))
                release(taken)
                controller(base,state)
                assert inventory()[block][1] == total and storage(block,total)["committed"] == 0
        if mode == "MODIFIED":
            delta = [word(state+i*8).value-interior_before[i-51] for i in range(51,56)]
            assert delta[:2] == [18,12] and delta[4] == 3, delta
            assert delta[2] == 12*total and delta[3] == 13*4096*3, delta
        word(state+8).value = reserve
        controller(base,state)
    finally:
        word(state).value, word(state+8).value = magic, reserve
        write(base+0x15f12c,install_bytes,True)
        write(alloc_slot,bytes(u64(old_alloc)))
        write(free_slot,bytes(u64(old_free)))
        for p,raw in saved.items(): C.memmove(p,raw,len(raw))
        for address,header,size in parked:
            add(address,header)
            word(base+0x27c808).value += size
        enable()
    assert all(C.string_at(p,len(raw)) == raw for p,raw in saved.items())
    action("CheckCells")
    result = dict(mode=mode,runtimeSHA256=expected,rows=rows,blacklistsRestored=True,
                  originalIATRestored=True,originalInstallHeaderRestored=True,liveAliasesVerified=True,
                  allocationAndBlacklisting="original-GC_allochblk_nth",gameCalls=0,gameWrites=0,gameBenefitBytes=None)
    (HERE/(mode+"_INTERIOR.json")).write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    gross = sum(r["commitBytes"] for r in rows if r["label"] in ("cold-small","cold-large","cold-nine-pages"))
    print(f"INTERIOR_PASS mode={mode} cases=27 ordinaryCommitBytes={gross} placement=original VM=closed blacklists=restored live=verified")


if __name__ == "__main__":
    main(sys.argv[1])
