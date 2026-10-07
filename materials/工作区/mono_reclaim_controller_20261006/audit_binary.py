"""Read the exact native retirement/caller bodies; no execution or game writes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/pydeps"))
import capstone
import pefile


def main() -> None:
    path = ROOT / "Mono/EmbedRuntime/mono.dll"
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == "cd7ab354a43faf18479c3a2d1f57d2d068769b8a490338942f6c510e8b02242d"
    pe = pefile.PE(data=data)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    ranges = [(0x15FC90, 0x15FD30), (0x157D00, 0x157F60),
              (0x15EB8C, 0x15ED20), (0x15EE50, 0x15EEA0)]
    report = {"sha256": hashlib.sha256(data).hexdigest(), "bodies": {},
              "imports": {}, "sections": [], "callers": []}
    for lo, hi in ranges:
        lines = [f"{i.address:08x}: {i.bytes.hex():20} {i.mnemonic} {i.op_str}"
                 for i in md.disasm(pe.get_data(lo, hi - lo), lo)]
        report["bodies"][hex(lo)] = lines
        print("---", hex(lo))
        print("\n".join(lines))
    for group in pe.DIRECTORY_ENTRY_IMPORT:
        for entry in group.imports:
            if entry.name and entry.name in (b"VirtualFree", b"VirtualAlloc"):
                report["imports"][entry.name.decode()] = hex(entry.address - pe.OPTIONAL_HEADER.ImageBase)
    for s in pe.sections:
        report["sections"].append({"name": s.Name.rstrip(b"\0").decode(),
            "rva": s.VirtualAddress, "vsize": s.Misc_VirtualSize,
            "rawSize": s.SizeOfRawData, "rawOffset": s.PointerToRawData})
    # Linear disassembly stops at embedded data. Enumerate exact rel32 encodings,
    # then decode each match; do not mistake an incomplete walk for zero callers.
    for s in pe.sections:
        if s.Characteristics & 0x20000000:
            block = s.get_data()
            for offset in range(len(block) - 4):
                if block[offset] != 0xE8:
                    continue
                rva = s.VirtualAddress + offset
                target = rva + 5 + int.from_bytes(block[offset+1:offset+5], "little", signed=True)
                if target == 0x15FC90:
                    instruction = next(md.disasm(block[offset:offset+5], rva))
                    assert instruction.mnemonic == "call"
                    report["callers"].append(hex(rva))
    assert report["callers"] == ["0x157ec4"]
    print("CALLERS", report["callers"])
    print("IMPORTS", report["imports"])
    print("SECTIONS", report["sections"])
    (Path(__file__).parent / "AUDIT.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
