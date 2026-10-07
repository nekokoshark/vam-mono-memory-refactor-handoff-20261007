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
    baseline = Path(__file__).parent / "BASELINE.dll"
    path = baseline if baseline.exists() else ROOT / "Mono/EmbedRuntime/mono.dll"
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == "cd7ab354a43faf18479c3a2d1f57d2d068769b8a490338942f6c510e8b02242d"
    pe = pefile.PE(data=data)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    ranges = [(0x15FC90, 0x15FD15), (0x157D34, 0x157EF8),
              (0x15EB8C, 0x15EC4E), (0x15EE50, 0x15EE94),
              (0x15892C, 0x158A16), (0x161578, 0x1615F1),
              (0x161270, 0x16134A), (0x161364, 0x161391),
              (0x1587AC, 0x15892C), (0x1580E8, 0x1582BB),
              (0x15FD18, 0x15FECA), (0x160004, 0x16044C),
              (0x15FECC, 0x15FF4D), (0x15F12C, 0x15F1BF),
              (0x15FA24, 0x15FB06), (0x15FC04, 0x15FC90),
              (0x158E8C, 0x158EB5), (0x158EB8, 0x158EE1),
              (0x157EF8, 0x157FC9)]
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
    assert pe.get_data(0x157F02, 11) == bytes.fromhex("48813dbb1c110000100000")
    assert pe.get_data(0x157F4C, 7) == bytes.fromhex("488915751c1100")
    report["heapSections"] = {"countRVA": "0x269bc8", "tableRVA": "0x281ac8",
                             "entryBytes": 16, "limit": 4096,
                             "registrationRVA": "0x157ef8", "decrementInRegistration": False}
    print("CALLERS", report["callers"])
    print("IMPORTS", report["imports"])
    print("SECTIONS", report["sections"])
    (Path(__file__).parent / "AUDIT.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
