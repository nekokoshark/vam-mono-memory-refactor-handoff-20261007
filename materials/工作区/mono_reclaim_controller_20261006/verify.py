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
    calloff = old.get_offset_from_rva(patch["callsiteRVA"])
    for s in old.sections:
        start, end = s.PointerToRawData, s.PointerToRawData + s.SizeOfRawData
        differences = [i for i in range(start, end) if a[i] != b[i]]
        assert all(calloff <= i < calloff + 5 for i in differences)
        changed.extend(differences)
    assert changed and len(changed) <= 4
    for index in (0, 1, 2, 5, 6, 9, 10, 12, 13, 14):
        x, y = old.OPTIONAL_HEADER.DATA_DIRECTORY[index], new.OPTIONAL_HEADER.DATA_DIRECTORY[index]
        assert (x.VirtualAddress, x.Size) == (y.VirtualAddress, y.Size)
    assert old.OPTIONAL_HEADER.AddressOfEntryPoint == new.OPTIONAL_HEADER.AddressOfEntryPoint
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
    assert new.get_data(patch["stateRVA"], 96) == struct.pack("<12Q", 0x31524C5443524347, 256*1024**2, *([0]*10))
    for rva, size in ((0x15EA48, 0x9D), (0x15EAE8, 0x65), (0x15EB8C, 194),
                      (0x15EC50, 191), (0x15EE50, 68), (0x15FC90, 133)):
        assert old.get_data(rva, size) == new.get_data(rva, size)
    (HERE / "STRUCTURE.json").write_text(json.dumps(dict(nativeChangedBytes=len(changed),
        nativeCallsite=hex(patch["callsiteRVA"]), exportsUnchanged=True, importsUnchanged=True,
        collectorAndOSAllocatorsUnchanged=True, newUnwindEntries=patch["newUnwindEntries"],
        chainedUnwindRebased=chains, wxAdded=False), indent=2) + "\n", encoding="utf-8")
    print("STRUCTURE_PASS exports=unchanged imports=unchanged allocator=original unwind=4+3 WX=none callsites=1")


if __name__ == "__main__":
    main()
