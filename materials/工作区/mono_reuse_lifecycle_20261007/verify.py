"""Compare to installed A1, not an older unmodified collector."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tools/pydeps"))
import capstone
import pefile


def main() -> None:
    old_patch = json.loads((HERE / "BASELINE_PATCH.json").read_text(encoding="utf-8"))
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    declaration = (HERE / "reclaim_controller.c").read_text(encoding="utf-8").split(
        "typedef struct ReclaimState {", 1)[1].split("} ReclaimState;", 1)[0]
    scalar_fields = re.findall(r"^\s*u64 (\w+);", declaration, flags=re.MULTILINE)
    assert len(scalar_fields) == 62 and "u64 warm_hints[32];" in declaration
    assert scalar_fields[:56] == old_patch["nativeStateFields"]
    assert scalar_fields + [f"warm_hints[{i}]" for i in range(32)] == patch["nativeStateFields"]
    a, b = (HERE / "BASELINE.dll").read_bytes(), (HERE / "MODIFIED_FILE.dll").read_bytes()
    assert hashlib.sha256(a).hexdigest() == patch["baselineSHA256"]
    assert hashlib.sha256(b).hexdigest() == patch["modifiedSHA256"]
    old, new = pefile.PE(data=a), pefile.PE(data=b)
    assert old.FILE_HEADER.NumberOfSections == new.FILE_HEADER.NumberOfSections
    sites = {r["rva"] for r in patch["callSites"]}
    assert sites - {r["rva"] for r in old_patch["callSites"]} == {0x161EBA}
    changed = []
    for section in old.sections[:-2]:
        start, end = section.PointerToRawData, section.PointerToRawData + section.SizeOfRawData
        differences = [i for i in range(start, end) if a[i] != b[i]]
        offsets = [old.get_offset_from_rva(rva) for rva in sites]
        assert all(any(off <= i < off + 5 for off in offsets) for i in differences)
        changed.extend(differences)
    assert old.OPTIONAL_HEADER.AddressOfEntryPoint == new.OPTIONAL_HEADER.AddressOfEntryPoint
    for index in (0, 1, 2, 5, 6, 9, 10, 12, 13, 14):
        x, y = old.OPTIONAL_HEADER.DATA_DIRECTORY[index], new.OPTIONAL_HEADER.DATA_DIRECTORY[index]
        assert (x.VirtualAddress, x.Size) == (y.VirtualAddress, y.Size)
    assert [(e.name, e.ordinal, e.address) for e in old.DIRECTORY_ENTRY_EXPORT.symbols] == [(e.name, e.ordinal, e.address) for e in new.DIRECTORY_ENTRY_EXPORT.symbols]
    assert [(g.dll, [(e.name, e.ordinal, e.address) for e in g.imports]) for g in old.DIRECTORY_ENTRY_IMPORT] == [(g.dll, [(e.name, e.ordinal, e.address) for e in g.imports]) for g in new.DIRECTORY_ENTRY_IMPORT]
    for rva, count in ((0x160004, 0x448), (0x16060C, 0x68), (0x1587AC, 0x180),
                       (0x15EB8C, 194), (0x15EC50, 191), (0x157EF8, 0xD1)):
        before, after = bytearray(old.get_data(rva, count)), bytearray(new.get_data(rva, count))
        for site in sites:
            if rva <= site and site + 5 <= rva + count:
                before[site-rva:site-rva+5] = after[site-rva:site-rva+5] = b"\0" * 5
        assert before == after, hex(rva)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    for row in patch["callSites"]:
        instruction = next(md.disasm(new.get_data(row["rva"], 5), row["rva"]))
        assert instruction.mnemonic == "call" and instruction.operands[0].imm == row["stubRVA"]
    address = patch["stubs"]["reuse_small"]
    instructions = list(md.disasm(new.get_data(address, 33), address))
    assert [i.mnemonic for i in instructions] == ["sub", "lea", "lea", "mov", "call", "add", "ret"]
    assert instructions[0].op_str == "rsp, 0x38"
    assert [i.address + i.size + i.operands[1].mem.disp for i in instructions if i.mnemonic == "lea"] == [0, patch["stateRVA"]]
    assert instructions[-3].operands[0].imm == patch["exports"]["reuse_small"]
    assert instructions[3].op_str == "qword ptr [rsp + 0x20], rax"
    rows = [(e.struct.BeginAddress, e.struct.EndAddress, e.struct.UnwindData) for e in new.DIRECTORY_ENTRY_EXCEPTION]
    assert rows == sorted(rows) and all(x[1] <= y[0] for x, y in zip(rows, rows[1:]))
    assert (address, address + 33, patch["thunkUnwindRVA"]) in rows
    chains = 0
    for begin, end, info_rva in rows:
        info = new.get_data(info_rva, 4)
        if begin >= patch["sections"][0]["rva"] and info[0] >> 3 == 4:
            at = info_rva + (4 + info[2] * 2 + 3) // 4 * 4
            assert struct.unpack("<III", new.get_data(at, 12)) in rows
            chains += 1
    assert chains == patch["chainedUnwindRecords"]
    assert patch["stateBytes"] == 94 * 8
    assert new.get_data(patch["stateRVA"], patch["stateBytes"]) == struct.pack("<94Q", 0x31524C5443524347, 256 * 1024**2, *([0] * 92))
    assert not any(s.Characteristics & 0x20000000 and s.Characteristics & 0x80000000 for s in new.sections)
    assert new.OPTIONAL_HEADER.CheckSum == new.generate_checksum()
    (HERE / "STRUCTURE.json").write_text(json.dumps(dict(nativeChangedBytes=len(changed),
        importsUnchanged=True, exportsUnchanged=True, newCallsite="0x161eba",
        originalNthUnchanged=True, originalGrowthUnchanged=True, originalSectionLimit=4096,
        hintBytes=256, originalFieldPrefixWords=56, hintWordOffset=62,
        stateWords=94, gameModified=False), indent=2) + "\n", encoding="utf-8")
    print("STRUCTURE_PASS A1=bound callsites=7 new=0x161eba originalNth+growth=unchanged WX=none stateWords=94")


if __name__ == "__main__":
    main()
