"""Verify preservation of the native ABI, loader structures and controller graft."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools/pydeps"))
import capstone
import pefile


def main() -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    a, b = (HERE / "BASELINE.dll").read_bytes(), (HERE / "MODIFIED_FILE.dll").read_bytes()
    assert hashlib.sha256(a).hexdigest() == patch["baselineSHA256"]
    assert hashlib.sha256(b).hexdigest() == patch["modifiedSHA256"]
    old, new = pefile.PE(data=a), pefile.PE(data=b)
    changed = []
    offsets = [old.get_offset_from_rva(row["rva"]) for row in patch["callSites"]]
    edit_offsets = [(old.get_offset_from_rva(e["rva"]),len(bytes.fromhex(e["original"]))) for e in patch["staticEdits"]]
    for e in patch["staticEdits"]:
        assert old.get_data(e["rva"],len(bytes.fromhex(e["original"]))).hex() == e["original"]
        assert new.get_data(e["rva"],len(bytes.fromhex(e["modified"]))).hex() == e["modified"]
    for s in old.sections:
        start, end = s.PointerToRawData, s.PointerToRawData + s.SizeOfRawData
        differences = [i for i in range(start, end) if a[i] != b[i]]
        assert all(any(calloff <= i < calloff + 5 for calloff in offsets) or any(start <= i < start+count for start,count in edit_offsets) for i in differences)
        changed.extend(differences)
    assert changed and len(changed) <= 39
    for index in (0, 1, 2, 5, 6, 9, 10, 12, 13, 14):
        x, y = old.OPTIONAL_HEADER.DATA_DIRECTORY[index], new.OPTIONAL_HEADER.DATA_DIRECTORY[index]
        assert (x.VirtualAddress, x.Size) == (y.VirtualAddress, y.Size)
    assert old.OPTIONAL_HEADER.AddressOfEntryPoint == new.OPTIONAL_HEADER.AddressOfEntryPoint
    assert old.get_data(0x157EF8, 0xD1) == new.get_data(0x157EF8, 0xD1)
    assert new.get_data(0x157F02, 11) == bytes.fromhex("48813dbb1c110000100000")
    assert [(e.name, e.ordinal, e.address) for e in old.DIRECTORY_ENTRY_EXPORT.symbols] == \
           [(e.name, e.ordinal, e.address) for e in new.DIRECTORY_ENTRY_EXPORT.symbols]
    assert [(g.dll, [(e.name, e.ordinal, e.address) for e in g.imports]) for g in old.DIRECTORY_ENTRY_IMPORT] == \
           [(g.dll, [(e.name, e.ordinal, e.address) for e in g.imports]) for g in new.DIRECTORY_ENTRY_IMPORT]
    assert new.OPTIONAL_HEADER.CheckSum == new.generate_checksum()
    assert new.FILE_HEADER.NumberOfSections == old.FILE_HEADER.NumberOfSections + 2
    assert not any(s.Characteristics & 0x20000000 and s.Characteristics & 0x80000000 for s in new.sections[-2:])
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    call = next(md.disasm(new.get_data(patch["callsiteRVA"], 5), patch["callsiteRVA"]))
    assert call.mnemonic == "call" and call.operands[0].imm == patch["stubRVA"]
    stub = list(md.disasm(new.get_data(patch["stubRVA"], 19), patch["stubRVA"]))
    assert [i.mnemonic for i in stub] == ["lea", "lea", "jmp"]
    assert stub[0].address + stub[0].size + stub[0].operands[1].mem.disp == 0
    assert stub[1].address + stub[1].size + stub[1].operands[1].mem.disp == patch["stateRVA"]
    assert stub[2].operands[0].imm == patch["controllerRVA"]
    for row in patch["callSites"]:
        call = next(md.disasm(new.get_data(row["rva"], 5), row["rva"]))
        assert call.mnemonic == "call" and call.operands[0].imm == row["stubRVA"]
    for name, size, expected in (("grow_on_demand", 22, ["mov", "lea", "lea", "jmp"]),
            ("remember_remap", 36, ["sub", "mov", "lea", "lea", "mov", "call", "add", "ret"]),
            ("take_prefix", 38, ["sub", "lea", "mov", "lea", "mov", "call", "add", "ret"]),
            ("split_cold_extent",46,["sub","mov","mov","lea","mov","lea","mov","call","add","ret"])):
        instructions = list(md.disasm(new.get_data(patch["stubs"][name], size), patch["stubs"][name]))
        assert [i.mnemonic for i in instructions] == expected
        target = instructions[-1] if name == "grow_on_demand" else instructions[-3]
        assert target.operands[0].imm == patch["exports"][name]
        leas = [i for i in instructions if i.mnemonic == "lea"]
        assert [i.address+i.size+i.operands[1].mem.disp for i in leas] == [0, patch["stateRVA"]]
    rows = [(e.struct.BeginAddress, e.struct.EndAddress, e.struct.UnwindData)
            for e in new.DIRECTORY_ENTRY_EXCEPTION]
    assert rows == sorted(rows)
    assert rows[:len(old.DIRECTORY_ENTRY_EXCEPTION)] == \
           [(e.struct.BeginAddress, e.struct.EndAddress, e.struct.UnwindData) for e in old.DIRECTORY_ENTRY_EXCEPTION]
    chains = 0
    for begin, end, unwind in rows[len(old.DIRECTORY_ENTRY_EXCEPTION):]:
        assert patch["sections"][0]["rva"] <= begin < end < patch["sections"][1]["rva"]
        info = new.get_data(unwind, 4)
        assert info[0] & 7 == 1 and info[0] >> 3 in (0, 4)
        if info[0] >> 3 == 4:
            offset = unwind + (4 + 2*info[2] + 3) // 4 * 4
            assert struct.unpack("<III", new.get_data(offset, 12)) in rows
            chains += 1
    assert chains == patch["chainedUnwindRecords"]
    words = patch["stateBytes"] // 8
    assert words >= 29 and words * 8 == patch["stateBytes"]
    assert new.get_data(patch["stateRVA"], patch["stateBytes"]) == struct.pack(
        f"<{words}Q", 0x31524C5443524347, 256*1024**2, *([0]*(words-2)))
    for rva, size in ((0x15EA48, 0x9D), (0x15EAE8, 0x65), (0x15EB8C, 194),
                      (0x15EC50, 191), (0x15EE50, 68), (0x15FC90, 133)):
        assert old.get_data(rva, size) == new.get_data(rva, size)
    (HERE / "STRUCTURE.json").write_text(json.dumps(dict(nativeChangedBytes=len(changed),
        nativeCallsite=hex(patch["callsiteRVA"]), exportsUnchanged=True, importsUnchanged=True,
        collectorAndOSAllocatorsUnchanged=True, newUnwindEntries=patch["newUnwindEntries"],
        chainedUnwindRebased=chains, wxAdded=False), indent=2) + "\n", encoding="utf-8")
    assert new.get_data(patch["thunkUnwindRVA"], 8) == bytes.fromhex("0104010004620000")
    assert new.get_data(patch["splitUnwindRVA"],8) == bytes.fromhex("0104010004820000")
    split = list(md.disasm(new.get_data(patch["stubs"]["split_cold_extent"],46),patch["stubs"]["split_cold_extent"]))
    assert split[0].op_str == "rsp, 0x48"
    assert split[1].op_str == "eax, dword ptr [rsp + 0x70]"
    assert split[2].op_str == "dword ptr [rsp + 0x20], eax"
    assert split[4].op_str == "qword ptr [rsp + 0x28], rax"
    assert split[6].op_str == "qword ptr [rsp + 0x30], rax"
    print(f"STRUCTURE_PASS exports=unchanged imports=unchanged WX=none callsites=6 unwind={patch['newUnwindEntries']} chains={chains}")


if __name__ == "__main__":
    main()
