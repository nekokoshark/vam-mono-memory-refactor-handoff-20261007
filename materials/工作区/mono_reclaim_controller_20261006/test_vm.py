"""Exact Windows VM commitment for the already-audited GC OS allocation table."""
from __future__ import annotations

import ctypes as C
from pathlib import Path
import runpy

FIELDS = [("BaseAddress", C.c_uint64), ("AllocationBase", C.c_uint64),
          ("AllocationProtect", C.c_uint32), ("alignment1", C.c_uint32),
          ("RegionSize", C.c_uint64), ("State", C.c_uint32), ("Protect", C.c_uint32),
          ("Type", C.c_uint32), ("alignment2", C.c_uint32)]


class MemoryInfo(C.Structure):
    _fields_ = FIELDS


def capture(base: int) -> dict:
    # Table RVAs were bound to allocation writes in scene_vm_owners_20261003.
    assert C.c_int.from_address(base + 0x269D18).value == 0
    count = C.c_uint64.from_address(base + 0x269D28).value
    assert 0 < count <= 0x3000
    roots = list((C.c_uint64 * count).from_address(base + 0x2E0000))
    query_api = C.WinDLL("kernel32", use_last_error=True).VirtualQuery
    query_api.argtypes, query_api.restype = (C.c_void_p, C.POINTER(MemoryInfo), C.c_size_t), C.c_size_t
    assert C.sizeof(MemoryInfo) == 48

    def query(address: int) -> tuple[int, int, int, int, int]:
        info = MemoryInfo()
        assert query_api(address, C.byref(info), 48) == 48
        return (info.BaseAddress, info.AllocationBase, info.RegionSize, info.State, info.Type)

    core = runpy.run_path(str(Path(__file__).parent.parent / "allocator_growth_pair_20261006/MODIFIED_FILE.py"))
    totals, observed = core["mono_regions"](query, roots)
    assert count == C.c_uint64.from_address(base + 0x269D28).value
    assert roots == list((C.c_uint64 * count).from_address(base + 0x2E0000))
    assert all(query(address) == row for address, row in observed.items())
    return {key: value for key, value in totals.items() if key != "allocations"}
