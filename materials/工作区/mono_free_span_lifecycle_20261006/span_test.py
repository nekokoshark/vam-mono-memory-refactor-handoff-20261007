"""Exercise original Mono free-span metadata and real Windows VM in a child."""
from __future__ import annotations

import ctypes as C
import hashlib
import json
from pathlib import Path
import runpy
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = HERE.parent / "mono_reclaim_cohorts_20261006"
MIB = 1024**2
VM_CAPTURE = runpy.run_path(str(HERE.parent / "mono_allocator_lifecycle_20261006/test_vm.py"))["capture"]


class Region(C.Structure):
    _fields_ = [("base", C.c_void_p), ("allocation", C.c_void_p),
                ("allocationProtect", C.c_uint32), ("partition", C.c_uint16),
                ("bytes", C.c_size_t), ("state", C.c_uint32),
                ("protect", C.c_uint32), ("type", C.c_uint32)]


def main(mode: str) -> None:
    patch_file = HERE / "PATCH.json"
    patch = json.loads((patch_file if patch_file.exists() else PREVIOUS / "PATCH.json").read_text())
    previous = json.loads((PREVIOUS / "PATCH.json").read_text())
    filename = {"BASELINE": "BASELINE.dll", "MODIFIED": "MODIFIED_FILE.dll",
                "ROLLBACK": "rollback_copy/mono.dll"}[mode]
    expected = patch["modifiedSHA256"] if mode == "MODIFIED" else previous["modifiedSHA256"]
    path = HERE / filename
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    mono = C.CDLL(str(path))
    base = mono._handle
    ptr, u64 = C.c_void_p, C.c_uint64

    def native(rva: int, result, *args):
        return C.CFUNCTYPE(result, *args)(base + rva)

    def api(name: str, result, *args):
        function = getattr(mono, name)
        function.restype, function.argtypes = result, list(args)
        return function

    api("mono_set_assemblies_path", None, C.c_char_p)((str(HERE) + ";" + str(ROOT / "VaM_Data/Managed")).encode())
    api("mono_set_dirs", None, C.c_char_p, C.c_char_p)(str(ROOT / "VaM_Data/Managed").encode(), str(ROOT / "Mono/etc").encode())
    domain = api("mono_jit_init_version", ptr, C.c_char_p, C.c_char_p)(b"FreeSpanLifecycle", b"v2.0.50727")
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
    disable, enable = native(0x158eb8, None), native(0x158e8c, None)
    find = native(0x15ee50, ptr, u64)
    install = native(0x15f12c, ptr, u64)
    remove = native(0x15fa24, None, ptr, C.c_int)
    add = native(0x15fc04, None, u64, ptr)
    remap, unmap = native(0x15ec50, None, u64, u64), native(0x15eb8c, None, u64, u64)
    expand = native(0x1580e8, C.c_int, u64)
    runtime_patch = patch if mode == "MODIFIED" else previous
    controller = native(runtime_patch["exports"]["reclaim_controller"], None, ptr, ptr)
    state_address = base + runtime_patch["stateRVA"]

    def word(address: int):
        return u64.from_address(address)

    marker = word(base + 0x269f70).value
    lists = (u64 * 61).from_address(base + 0x269d70)

    def inventory() -> dict[int, tuple[int, int]]:
        found = {}
        for bucket in range(61):
            block, previous_block = lists[bucket], 0
            while block:
                h = find(block)
                assert h and h > 4096 and block not in found
                size = word(h).value
                assert word(h + 32).value == marker and size and not size % 4096
                assert word(h + 16).value == previous_block
                found[block] = (h, size)
                previous_block, block = block, word(h + 8).value
        assert sum(s for _, s in found.values()) == word(base + 0x27c808).value
        return found

    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.VirtualProtect.argtypes = (ptr, C.c_size_t, C.c_uint32, C.POINTER(C.c_uint32))
    kernel.VirtualProtect.restype = C.c_int
    kernel.VirtualQuery.argtypes, kernel.VirtualQuery.restype = (ptr, C.POINTER(Region), C.c_size_t), C.c_size_t
    alloc_type = C.WINFUNCTYPE(ptr, ptr, C.c_size_t, C.c_uint32, C.c_uint32)
    free_type = C.WINFUNCTYPE(C.c_int, ptr, C.c_size_t, C.c_uint32)
    alloc_slot, free_slot = base + 0x1901d8, base + 0x1901e0
    old_alloc, old_free = word(alloc_slot).value, word(free_slot).value
    real_alloc, real_free = alloc_type(old_alloc), free_type(old_free)
    events = []

    @alloc_type
    def observed_alloc(address, size, kind, protect):
        result = real_alloc(address, size, kind, protect)
        events.append(dict(op="commit", address=address, bytes=size, flags=kind, success=result == address))
        return result

    @free_type
    def observed_free(address, size, kind):
        result = real_free(address, size, kind)
        events.append(dict(op="decommit", address=address, bytes=size, flags=kind, success=bool(result)))
        return result

    def replace(address: int, value: int) -> None:
        protection = C.c_uint32()
        assert kernel.VirtualProtect(address, 8, 4, C.byref(protection))
        word(address).value = value
        ignored = C.c_uint32()
        assert kernel.VirtualProtect(address, 8, protection.value, C.byref(ignored))

    def storage(block: int, size: int) -> dict:
        cursor, committed, reserved = block, 0, 0
        while cursor < block + size:
            region = Region()
            assert kernel.VirtualQuery(cursor, C.byref(region), C.sizeof(region)) == C.sizeof(region)
            end = min(region.base + region.bytes, block + size)
            assert end > cursor and region.state in (0x1000, 0x2000)
            if region.state == 0x1000: committed += end - cursor
            else: reserved += end - cursor
            cursor = end
        return dict(committed=committed, reserved=reserved)

    rows = []
    disable()
    try:
        assert expand(512 * MIB // 4096)
        free = inventory()
        block, (h, total) = max(free.items(), key=lambda pair: pair[1][1])
        assert total >= 512 * MIB
        heap, sections, free_total = (word(base + rva).value for rva in (0x27c7e0, 0x269bc8, 0x27c808))
        reserve_original = word(state_address + 8).value
        replace(alloc_slot, C.cast(observed_alloc, ptr).value)
        replace(free_slot, C.cast(observed_free, ptr).value)
        # All four mixed directions, ties, homogeneous states, and three runs.
        cases = [(384*MIB, False, True, 256*MIB, "over-budget-left-warm"),
                 (128*MIB, True, False, 256*MIB, "over-budget-right-warm"),
                 (384*MIB, True, False, 256*MIB, "native-cold-left"),
                 (128*MIB, False, True, 256*MIB, "native-cold-right"),
                 (256*MIB, False, True, 256*MIB, "tie-left-warm"),
                 (256*MIB, True, False, 256*MIB, "tie-right-warm"),
                 (384*MIB, False, True, 768*MIB, "within-budget-left-warm"),
                 (128*MIB, True, False, 768*MIB, "within-budget-right-warm"),
                 (384*MIB, True, True, 256*MIB, "both-cold")]
        for cycle in range(3):
            for left, cold_left, cold_right, reserve, label in cases:
                h = find(block)
                assert word(h).value == total
                remove(h, -1)
                if C.c_ubyte.from_address(h + 41).value & 2: remap(block, total)
                right_h = install(block + left)
                assert right_h
                word(h).value, word(right_h).value = left, total-left
                for address, hdr, size, cold in ((block, h, left, cold_left), (block+left, right_h, total-left, cold_right)):
                    C.c_ubyte.from_address(hdr+41).value = 2 if cold else 0
                    if cold: unmap(address, size)
                    add(address, hdr)
                assert sum(size for _,size in inventory().values()) == free_total
                word(state_address+8).value = reserve
                before = storage(block,total)
                events.clear()
                started = time.perf_counter()
                controller(base,state_address)
                elapsed = (time.perf_counter()-started)*1000
                calls = [e for e in events if block <= e["address"] < block+total]
                commits = sum(e["bytes"] for e in calls if e["op"] == "commit")
                decommits = sum(e["bytes"] for e in calls if e["op"] == "decommit")
                after = storage(block,total)
                assert all(e["success"] for e in events)
                vm = VM_CAPTURE(base)
                assert vm["monoReservedBytes"] == word(base + 0x27ea88).value, (vm, label)
                assert before["committed"] + commits - decommits == after["committed"], (label,before,after,calls)
                merged = inventory()
                assert merged[block][1] == total and block+left not in merged
                assert word(base+0x27c7e0).value == heap and word(base+0x269bc8).value == sections
                if label.startswith("over-budget"):
                    assert after["committed"] == 0
                    assert commits == (0 if mode == "MODIFIED" else 128*MIB)
                if label.startswith("within-budget"): assert commits == 128*MIB and after["committed"] == total
                if label == "tie-right-warm": assert commits == (0 if mode == "MODIFIED" else 256*MIB)
                if label in ("native-cold-left", "native-cold-right", "tie-left-warm", "both-cold"):
                    assert commits == 0 and after["committed"] == 0
                if mode == "MODIFIED":
                    assert word(state_address + 48*8).value == 0
                    mapped_free = sum(size for hdr,size in merged.values() if not C.c_ubyte.from_address(hdr+41).value & 2)
                    assert word(state_address + 5*8).value == mapped_free <= reserve
                rows.append(dict(cycle=cycle,label=label,before=before,after=after,commitBytes=commits,
                                 decommitBytes=decommits,elapsedMs=elapsed,VMcalls=calls,globalVM=vm))
        word(state_address+8).value = reserve_original
        controller(base,state_address)
        inventory()
    finally:
        replace(alloc_slot,old_alloc)
        replace(free_slot,old_free)
        enable()
    action("CheckCells")
    action("DropCellRoots")
    api("mono_gc_collect",None,C.c_int)(0)
    result=dict(mode=mode,runtimeSHA256=expected,rows=rows,heapBytes=heap,sections=sections,
                originalIATRestored=True,originalReserveRestored=True,liveAliasesVerified=True,
                gameCalls=0,gameWrites=0,gameBenefitBytes=None)
    (HERE/(mode+"_SPANS.json")).write_text(json.dumps(result,indent=2)+"\n")
    gross=sum(r["commitBytes"] for r in rows if r["label"].startswith("over-budget"))
    print(f"SPAN_PASS mode={mode} cases=27 avoidableCommitBytes={gross} coalesced=True VM=closed sections=unchanged live=verified IAT=restored")


if __name__ == "__main__":
    main(sys.argv[1])
