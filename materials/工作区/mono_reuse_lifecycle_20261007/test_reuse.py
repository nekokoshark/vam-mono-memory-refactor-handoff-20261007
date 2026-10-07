"""Original GC_new_hblk, original blacklists and real VM; private child only."""
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
PRIOR = HERE.parent / "mono_interior_commit_lifecycle_20261007"
sys.path.insert(0, str(PRIOR))
from cohort_test import FIRST_FIELDS

MIB = 1024**2
VM_CAPTURE = runpy.run_path(str(HERE.parent / "mono_allocator_lifecycle_20261006/test_vm.py"))["capture"]


def main(mode: str) -> None:
    if mode not in ("BASELINE", "MODIFIED", "ROLLBACK"):
        raise ValueError("Unknown arm")
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    runtime = patch if mode == "MODIFIED" else json.loads((HERE / "BASELINE_PATCH.json").read_text(encoding="utf-8"))
    filename = {"BASELINE": "BASELINE.dll", "MODIFIED": "MODIFIED_FILE.dll", "ROLLBACK": "rollback_copy/mono.dll"}[mode]
    expected = patch["modifiedSHA256" if mode == "MODIFIED" else "baselineSHA256"]
    assert hashlib.sha256((HERE / filename).read_bytes()).hexdigest() == expected
    mono = C.CDLL(str(HERE / filename))
    base, ptr, u64 = mono._handle, C.c_void_p, C.c_uint64

    def api(name: str, result, *args):
        function = getattr(mono, name)
        function.restype, function.argtypes = result, list(args)
        return function

    def native(rva: int, result, *args):
        return C.CFUNCTYPE(result, *args)(base + rva)

    def word(address: int):
        return u64.from_address(address)

    def flags(header: int):
        return C.c_ubyte.from_address(header + 41)

    api("mono_set_assemblies_path", None, C.c_char_p)((str(HERE) + ";" + str(ROOT / "VaM_Data/Managed")).encode())
    api("mono_set_dirs", None, C.c_char_p, C.c_char_p)(str(ROOT / "VaM_Data/Managed").encode(), str(ROOT / "Mono/etc").encode())
    domain = api("mono_jit_init_version", ptr, C.c_char_p, C.c_char_p)(b"WarmReusePlacement", b"v2.0.50727")
    assert domain
    assembly = api("mono_domain_assembly_open", ptr, ptr, C.c_char_p)(domain, str(PRIOR / "LifecycleSample.dll").encode())
    image = api("mono_assembly_get_image", ptr, ptr)(assembly)
    klass = api("mono_class_from_name", ptr, ptr, C.c_char_p, C.c_char_p)(image, b"", b"LifecycleSample")
    method = api("mono_class_get_method_from_name", ptr, ptr, C.c_char_p, C.c_int)
    invoke = api("mono_runtime_invoke", ptr, ptr, ptr, ptr, C.POINTER(ptr))

    def action(name: str) -> None:
        error = ptr()
        assert invoke(method(klass, name.encode(), 0), None, None, C.byref(error)) and not error.value

    action("PrepareCells")
    find = native(0x15EE50, ptr, u64)
    expand = native(0x1580E8, C.c_int, u64)
    allocate = native(0x160004, ptr, u64, C.c_int, C.c_ubyte, C.c_int)
    release = native(0x16044C, None, u64)
    remove, add = native(0x15FA24, None, ptr, C.c_int), native(0x15FC04, None, u64, ptr)
    remap, unmap = native(0x15EC50, None, u64, u64), native(0x15EB8C, None, u64, u64)
    new_hblk = native(0x161E74, None, u64, C.c_int)
    disable, enable = native(0x158EB8, None), native(0x158E8C, None)
    state_address = base + runtime["stateRVA"]
    controller = native(runtime["exports"]["reclaim_controller"], None, ptr, ptr)
    names = FIRST_FIELDS + tuple(runtime["extraStateFields"])
    marker = word(base + 0x269F70).value
    lists = (u64 * 61).from_address(base + 0x269D70)

    def state() -> dict:
        return dict(zip(names, (u64 * len(names)).from_address(state_address)))

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
        assert sum(size for _, size in found.values()) == word(base + 0x27C808).value
        return found

    bitmaps = {word(base + rva).value for rva in (0x26C448, 0x26C450, 0x26C458, 0x26C460)}
    assert all(address > 4096 for address in bitmaps)
    saved_bitmaps = {address: C.string_at(address, 131072) for address in bitmaps}
    stack_blacklist = word(base + 0x26C458).value
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.VirtualProtect.argtypes, kernel.VirtualProtect.restype = (ptr, C.c_size_t, C.c_uint32, C.POINTER(C.c_uint32)), C.c_int
    alloc_type = C.WINFUNCTYPE(ptr, ptr, C.c_size_t, C.c_uint32, C.c_uint32)
    slot = base + 0x1901D8
    original_alloc = word(slot).value
    actual_alloc = alloc_type(original_alloc)
    events = []

    @alloc_type
    def observed_alloc(address, size, kind, protect):
        result = actual_alloc(address, size, kind, protect)
        events.append(dict(address=address, bytes=size, flags=kind, success=bool(result)))
        return result

    def replace_slot(value: int) -> None:
        protection, ignored = C.c_uint32(), C.c_uint32()
        assert kernel.VirtualProtect(slot, 8, 4, C.byref(protection))
        word(slot).value = value
        assert kernel.VirtualProtect(slot, 8, protection.value, C.byref(ignored))

    guards, cold_pages, parked, rows = [], [], [], []
    allocated = []
    disable()
    try:
        for address in bitmaps:
            C.memset(address, 0, 131072)
        assert expand(512 * MIB // 4096)
        block, (_, total) = max(inventory().items(), key=lambda pair: pair[1][1])
        # Park unrelated long spans so fixture construction follows one extent.
        for address, (header, size) in list(inventory().items()):
            if address != block:
                remove(header, -1)
                word(base + 0x27C808).value -= size
                parked.append((address, header, size))
        for _ in range(16):
            page = allocate(512, 0, 0, 60)
            guard = allocate(512, 0, 0, 60)
            assert page and guard
            cold_pages.append(page)
            guards.append(guard)
        warm = allocate(8192, 0, 0, 60)
        guard = allocate(512, 0, 0, 60)
        assert warm and guard
        guards.append(guard)
        for page in cold_pages:
            release(page)
        release(warm)
        # Exactly one mapped 64-KiB extent and 16 separated cold 4-KiB extents.
        for address, (header, size) in inventory().items():
            if address != warm:
                unmap(address, size)
                flags(header).value |= 2
        assert inventory()[warm][1] == 65536 and lists[1] in cold_pages
        heap, sections, free_total = (word(base + rva).value for rva in (0x27C7E0, 0x269BC8, 0x27C808))
        replace_slot(C.cast(observed_alloc, ptr).value)
        for label, kind in (("normal", 0), ("blacklisted-leading", 1), ("stale-hint", 0),
                            ("invalid-context", 0), ("uncollectable", 2)):
            for address, (header, size) in inventory().items():
                if address == warm:
                    if flags(header).value & 2:
                        remap(address, size)
                    flags(header).value &= ~2
                elif not flags(header).value & 2:
                    unmap(address, size)
                    flags(header).value |= 2
            for address in bitmaps:
                C.memset(address, 0, 131072)
            if label == "blacklisted-leading":
                bit = (warm // 4096) & 0xFFFFF
                word(stack_blacklist + 8 * (bit // 64)).value |= 1 << (bit % 64)
            controller(base, state_address)
            before = state()
            assert inventory()[warm][1] == 65536 and not flags(find(warm)).value & 2
            if mode == "MODIFIED" and label == "stale-hint":
                hints = (u64 * 32).from_address(state_address + 62 * 8)
                assert hints[15] == (~warm & 0xFFFFFFFFFFFFFFFF)
                hints[15] = ~guards[0] & 0xFFFFFFFFFFFFFFFF
            magic = word(state_address).value
            if label == "invalid-context":
                word(state_address).value = 0
            free_list = word(base + 0x2659A0 + kind * 32).value
            free_head = word(free_list + 32 * 8)
            original_head = free_head.value
            events.clear()
            started = time.perf_counter()
            for number in range(16):
                new_hblk(32, kind)
                head = free_head.value
                assert head and head != original_head
                page = head & ~4095
                free_head.value = original_head
                assert page not in allocated and (page in cold_pages or warm <= page < warm + 65536)
                allocated.append(page)
                # No free-list consumer retains these test cells after restoration.
                word(page).value = 0x1234000000000000 + number
                word(page + 4088).value = 0x5678000000000000 + number
            elapsed = (time.perf_counter() - started) * 1000
            word(state_address).value = magic
            calls = [event for event in events if event["address"] and block <= event["address"] < block + total]
            commits = sum(event["bytes"] for event in calls)
            assert all(event["success"] for event in calls)
            expected_bytes = 65536
            if mode == "MODIFIED" and label == "normal":
                expected_bytes = 0
            elif mode == "MODIFIED" and label == "blacklisted-leading":
                expected_bytes = 4096
                assert warm not in allocated
            assert commits == expected_bytes, (label, commits, expected_bytes, allocated)
            for number, page in enumerate(allocated):
                assert word(page).value == 0x1234000000000000 + number
                assert word(page + 4088).value == 0x5678000000000000 + number
            assert word(base + 0x27C7E0).value == heap and word(base + 0x269BC8).value == sections
            assert sum(size for _, size in inventory().values()) == free_total - 65536
            vm = VM_CAPTURE(base)
            assert vm["monoReservedBytes"] == word(base + 0x27EA88).value
            after = state()
            rows.append(dict(case=label, nativeCommitBytes=commits, commitCalls=len(calls),
                allocations=16, payloadBytes=65536, elapsedMs=elapsed, before=before, after=after,
                heapUnchanged=True, sectionsUnchanged=True, liveBytesVerified=True, nativeVM=vm))
            for address in bitmaps:
                C.memset(address, 0, 131072)
            for page in allocated:
                release(page)
            allocated.clear()
            assert sum(size for _, size in inventory().values()) == free_total
        for address, raw in saved_bitmaps.items():
            C.memmove(address, raw, len(raw))
        for address, header, size in parked:
            add(address, header)
            word(base + 0x27C808).value += size
        parked.clear()
        inventory()
    finally:
        replace_slot(original_alloc)
        for address, raw in saved_bitmaps.items():
            C.memmove(address, raw, len(raw))
        for address, header, size in parked:
            add(address, header)
            word(base + 0x27C808).value += size
        enable()
    action("CheckCells")
    result = dict(mode=mode, runtimeSHA256=expected, rows=rows,
        originalNewHblkExecuted=True, originalNthExecuted=True, originalIATRestored=True,
        originalBlacklistsRestored=True, aliasesPreserved=True, gameWrites=0, gameCalls=0,
        measuredGameSavingsBytes=None)
    (HERE / (mode + "_REUSE.json")).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"REUSE_PASS mode={mode} cases=5 normalCommitBytes={rows[0]['nativeCommitBytes']} "
          f"blacklistCommitBytes={rows[1]['nativeCommitBytes']} heap=unchanged sections=unchanged aliases=verified VM=closed")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception:
        import traceback
        traceback.print_exc()
        raise SystemExit(70)
