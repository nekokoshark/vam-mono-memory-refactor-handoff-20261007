"""Check the loader's actual x64 unwind entries, including the seven-argument thunk."""
from __future__ import annotations

import ctypes as C
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def main(mode: str) -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    runtime = patch if mode == "MODIFIED" else json.loads(
        (HERE.parent / "mono_free_span_lifecycle_20261006/PATCH.json").read_text(encoding="utf-8"))
    path = HERE / {"BASELINE": "BASELINE.dll", "MODIFIED": "MODIFIED_FILE.dll",
                   "ROLLBACK": "rollback_copy/mono.dll"}[mode]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == patch[
        "modifiedSHA256" if mode == "MODIFIED" else "baselineSHA256"]
    mono = C.CDLL(str(path))
    ntdll = C.WinDLL("ntdll")
    ptr, u64 = C.c_void_p, C.c_uint64
    lookup = ntdll.RtlLookupFunctionEntry
    lookup.argtypes, lookup.restype = (u64, C.POINTER(u64), ptr), ptr
    unwind = ntdll.RtlVirtualUnwind
    unwind.argtypes, unwind.restype = (C.c_uint32, u64, u64, ptr, ptr,
                                     C.POINTER(ptr), C.POINTER(u64), ptr), ptr
    rows = []
    thunks = [("remember_remap", 56, 31), ("take_prefix", 56, 33)]
    if mode == "MODIFIED": thunks.append(("split_cold_extent", 72, 41))
    for name, frame, epilogue in thunks:
        address = mono._handle + runtime["stubs"][name]
        for offset in (0, 4, epilogue):
            stack = C.create_string_buffer(256)
            entry_rsp = (C.addressof(stack) + 15) // 16 * 16 + 136
            assert entry_rsp % 16 == 8
            sentinel = 0x123456789ABC
            u64.from_address(entry_rsp).value = sentinel
            context = C.create_string_buffer(0x4d0 + 16)
            ctx = (C.addressof(context) + 15) // 16 * 16
            C.c_uint32.from_address(ctx + 0x30).value = 0x100001
            u64.from_address(ctx + 0x98).value = entry_rsp if offset == 0 else entry_rsp-frame
            u64.from_address(ctx + 0xf8).value = address+offset
            image_base, handler, establisher = u64(), ptr(), u64()
            function = lookup(address+offset, C.byref(image_base), None)
            assert function and image_base.value == mono._handle
            assert not unwind(0, image_base.value, address+offset, function, ctx,
                              C.byref(handler), C.byref(establisher), None)
            assert u64.from_address(ctx+0x98).value == entry_rsp+8
            assert u64.from_address(ctx+0xf8).value == sentinel
            rows.append(dict(thunk=name, offset=offset, stackRestored=True, returnRestored=True))
    (HERE/(mode+"_ABI.json")).write_text(json.dumps(dict(mode=mode, rows=rows,
        registeredByWindowsLoader=True, gameWrites=0),indent=2)+"\n",encoding="utf-8")
    print(f"ABI_PASS mode={mode} unwindCases={len(rows)} stack=restored return=restored loader=registered")


if __name__ == "__main__":
    main(sys.argv[1])
