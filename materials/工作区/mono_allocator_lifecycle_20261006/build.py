"""Compile an ABI-preserving native controller and graft RX/RW PE sections."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools/pydeps"))
import pefile

BASE_SHA = "cd7ab354a43faf18479c3a2d1f57d2d068769b8a490338942f6c510e8b02242d"
MSVC = Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64")


def align(n: int, alignment: int) -> int:
    return (n + alignment - 1) & -alignment


def command(argv: list[str], records: list[dict]) -> None:
    run = subprocess.run(argv, cwd=HERE, capture_output=True, text=True, timeout=120)
    records.append({"argv": argv, "stdout": run.stdout, "stderr": run.stderr,
                    "exitStatus": run.returncode})
    if run.returncode:
        raise RuntimeError(run.stdout + run.stderr)


def main(output_dir: Path | None = None, state_words: int = 29,
         controller_section_alignment: int = 4096) -> None:
    global HERE
    if output_dir is not None:
        HERE = output_dir.resolve()
    if state_words < 29:
        raise ValueError("Controller state must preserve its first 29 words")
    if controller_section_alignment < 4096 or controller_section_alignment & (controller_section_alignment - 1):
        raise ValueError("Controller alignment must be a page-aligned power of two")
    baseline = HERE / "BASELINE.dll"
    source = baseline if baseline.exists() else ROOT / "Mono/EmbedRuntime/mono.dll"
    original = source.read_bytes()
    assert hashlib.sha256(original).hexdigest() == BASE_SHA
    if not baseline.exists():
        baseline.write_bytes(original)
    records: list[dict] = []
    command([str(MSVC / "cl.exe"), "/nologo", "/c", "/O2", "/GS-", "/Zl",
             "/W4", "/WX", "/Brepro", "/Foreclaim_controller.obj", "reclaim_controller.c"], records)
    link_alignment = [] if controller_section_alignment == 4096 else [f"/align:{controller_section_alignment}"]
    command([str(MSVC / "link.exe"), "/nologo", "/dll", "/noentry", "/nodefaultlib",
             "/machine:x64", "/dynamicbase", "/nxcompat", "/opt:ref", "/opt:icf",
             "/Brepro", "/out:controller_image.dll", *link_alignment, "reclaim_controller.obj"], records)
    image = pefile.PE(data=(HERE / "controller_image.dll").read_bytes())
    assert not image.OPTIONAL_HEADER.DATA_DIRECTORY[1].Size, "Controller must have no imports"
    assert not image.OPTIONAL_HEADER.DATA_DIRECTORY[5].Size, "Controller must be position independent"
    exports = {e.name.decode(): e.address for e in image.DIRECTORY_ENTRY_EXPORT.symbols}
    assert set(exports) == {"reclaim_controller", "remember_remap", "take_prefix", "grow_on_demand"}
    code = next(s for s in image.sections if s.Name.rstrip(b"\0") == b".text")
    other = [s for s in image.sections if s is not code]
    assert all(s.Name.rstrip(b"\0") in (b".rdata", b".data", b".pdata") for s in other)
    assert all(s.Misc_VirtualSize <= 8 and not s.SizeOfRawData
               for s in other if s.Name.rstrip(b"\0") == b".data")
    pe = pefile.PE(data=original)
    assert pe.FILE_HEADER.Machine == 0x8664
    assert pe.get_data(0x157EC4, 5) == bytes.fromhex("e8c77d0000")
    audit = json.loads((HERE / "AUDIT.json").read_text(encoding="utf-8"))
    assert audit["sha256"] == BASE_SHA and audit["callers"] == ["0x157ec4"]
    assert pe.get_data(0x15FC90, 133).hex() == "".join(line.split(": ")[1].split()[0]
        for line in audit["bodies"]["0x15fc90"] if int(line.split(":")[0], 16) < 0x15FD15)

    section_alignment = pe.OPTIONAL_HEADER.SectionAlignment
    file_alignment = pe.OPTIONAL_HEADER.FileAlignment
    new_rva = align(pe.OPTIONAL_HEADER.SizeOfImage, section_alignment)
    delta = new_rva - code.VirtualAddress
    text = bytearray(code.get_data())
    stub_offset = align(code.Misc_VirtualSize, 16)
    stub_rva = new_rva + stub_offset
    data_rva = min(s.VirtualAddress for s in other) + delta
    # Four ABI thunks: two leaf tailcalls and two stack-argument calls.
    stubs = {"reclaim_controller": stub_rva, "grow_on_demand": stub_rva + 32,
             "remember_remap": stub_rva + 64, "take_prefix": stub_rva + 112}
    assert stub_rva + 160 < data_rva
    text.extend(b"\0" * max(0, stub_offset + 160 - len(text)))

    # Keep donor relative code/data distances. No new absolute pointers/relocs.
    payload_end = max(s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData) for s in other) + delta
    state_rva = align(payload_end, 8)
    state_size = state_words * 8
    old_directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    old_rows = [struct.unpack_from("<III", pe.get_data(old_directory.VirtualAddress, old_directory.Size), n)
                for n in range(0, old_directory.Size, 12)]
    new_rows = []
    chained_records = []
    for entry in image.DIRECTORY_ENTRY_EXCEPTION:
        row = entry.struct
        info = image.get_data(row.UnwindData, 4)
        flags = info[0] >> 3
        assert info[0] & 7 == 1 and flags in (0, 4), "Unexpected unwind version/exception handler"
        if flags == 4:
            chain_rva = row.UnwindData + align(4 + info[2] * 2, 4)
            chain = struct.unpack("<III", image.get_data(chain_rva, 12))
            assert chain in [(e.struct.BeginAddress, e.struct.EndAddress, e.struct.UnwindData)
                             for e in image.DIRECTORY_ENTRY_EXCEPTION]
            chained_records.append((chain_rva + delta, tuple(v + delta for v in chain)))
        new_rows.append((row.BeginAddress + delta, row.EndAddress + delta, row.UnwindData + delta))
    # Manually described thunks have a single SUB RSP,56 prologue and no saves.
    thunk_unwind_rva = align(state_rva + state_size, 4)
    for name, size in (("remember_remap", 36), ("take_prefix", 38)):
        new_rows.append((stubs[name], stubs[name] + size, thunk_unwind_rva))
    rows = sorted(old_rows + new_rows)
    assert all(a[0] < a[1] <= b[0] for a, b in zip(rows, rows[1:])), "Overlapping unwind ranges"
    table_rva = thunk_unwind_rva + 8
    table = b"".join(struct.pack("<III", *row) for row in rows)
    data = bytearray(table_rva + len(table) - data_rva)
    for s in other:
        off = s.VirtualAddress + delta - data_rva
        data[off:off+s.SizeOfRawData] = s.get_data()
    for rva, chain in chained_records:
        struct.pack_into("<III", data, rva - data_rva, *chain)
    struct.pack_into(f"<{state_words}Q", data, state_rva - data_rva,
                     0x31524C5443524347, 256 * 1024**2, *([0] * (state_words - 2)))
    data[thunk_unwind_rva-data_rva:thunk_unwind_rva-data_rva+8] = bytes.fromhex("0104010004620000")
    data[table_rva-data_rva:] = table
    # Leaf thunk: establish module base/context without changing stack or ABI.
    stub = (b"\x48\x8d\x0d" + struct.pack("<i", -(stub_rva + 7)) +
            b"\x48\x8d\x15" + struct.pack("<i", state_rva - (stub_rva + 14)) +
            b"\xe9" + struct.pack("<i", exports["reclaim_controller"] + delta - (stub_rva + 19)))
    text[stub_offset:stub_offset+len(stub)] = stub
    def rel(rva: int, target: int) -> bytes:
        return struct.pack("<i", target - rva)
    grow = stubs["grow_on_demand"]
    stub = (bytes.fromhex("4889da4c8d05") + rel(grow+10, 0) +
            bytes.fromhex("4c8d0d") + rel(grow+17, state_rva) + b"\xe9" +
            rel(grow+22, exports["grow_on_demand"]+delta))
    text[grow-new_rva:grow-new_rva+len(stub)] = stub
    remember = stubs["remember_remap"]
    stub = (bytes.fromhex("4883ec384c8bc64c8d0d") + rel(remember+14, 0) +
            bytes.fromhex("488d05") + rel(remember+21, state_rva) +
            bytes.fromhex("4889442420e8") + rel(remember+31, exports["remember_remap"]+delta) +
            bytes.fromhex("4883c438c3"))
    assert len(stub) == 36
    text[remember-new_rva:remember-new_rva+len(stub)] = stub
    take = stubs["take_prefix"]
    stub = (bytes.fromhex("4883ec38488d05") + rel(take+11, 0) +
            bytes.fromhex("4889442420488d05") + rel(take+23, state_rva) +
            bytes.fromhex("4889442428e8") + rel(take+33, exports["take_prefix"]+delta) +
            bytes.fromhex("4883c438c3"))
    assert len(stub) == 38
    text[take-new_rva:take-new_rva+len(stub)] = stub
    assert len(text) <= data_rva - new_rva

    candidate = bytearray(original)
    sites = [(0x157EC4, 0x15FC90, "reclaim_controller"),
             (0x1603B6, 0x15EC50, "remember_remap"),
             (0x1603CB, 0x15FECC, "take_prefix"),
             (0x158890, 0x1580E8, "grow_on_demand"),
             (0x15889C, 0x1580E8, "grow_on_demand")]
    for site, old_target, name in sites:
        call_offset = pe.get_offset_from_rva(site)
        assert pe.get_data(site, 5) == b"\xe8" + rel(site+5, old_target)
        candidate[call_offset:call_offset+5] = b"\xe8" + rel(site+5, stubs[name])
    headers = pe.sections[-1].get_file_offset() + 40
    assert headers + 80 <= pe.OPTIONAL_HEADER.SizeOfHeaders
    assert not any(candidate[headers:headers+80]), "No spare PE section headers"
    raw = align(len(candidate), file_alignment)
    candidate.extend(b"\0" * (raw - len(candidate)))
    descriptions = []
    for index, (name, rva, content, flags) in enumerate([
            (b".gcrtext", new_rva, text, 0x60000020),
            (b".gcrdat", data_rva, data, 0xC0000040)]):
        size = align(len(content), file_alignment)
        header = struct.pack("<8sIIIIIIHHI", name, len(content), rva, size, raw, 0, 0, 0, 0, flags)
        candidate[headers+index*40:headers+(index+1)*40] = header
        candidate.extend(content + b"\0" * (size - len(content)))
        descriptions.append({"name": name.decode(), "rva": rva, "rawOffset": raw, "bytes": len(content)})
        raw += size
    rewritten = pefile.PE(data=bytes(candidate))
    rewritten.FILE_HEADER.NumberOfSections += 2
    rewritten.OPTIONAL_HEADER.SizeOfImage = align(data_rva + len(data), section_alignment)
    rewritten.OPTIONAL_HEADER.SizeOfCode += align(len(text), file_alignment)
    rewritten.OPTIONAL_HEADER.SizeOfInitializedData += align(len(data), file_alignment)
    rewritten.OPTIONAL_HEADER.DATA_DIRECTORY[3].VirtualAddress = table_rva
    rewritten.OPTIONAL_HEADER.DATA_DIRECTORY[3].Size = len(table)
    # Modified binaries do not retain a claim to the original signed digest.
    rewritten.OPTIONAL_HEADER.DATA_DIRECTORY[4].VirtualAddress = 0
    rewritten.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size = 0
    rewritten.OPTIONAL_HEADER.CheckSum = 0
    result = rewritten.write()
    checked = pefile.PE(data=result)
    checked.OPTIONAL_HEADER.CheckSum = checked.generate_checksum()
    result = checked.write()
    (HERE / "MODIFIED_FILE.dll").write_bytes(result)
    patch = {"baselineSHA256": BASE_SHA, "modifiedSHA256": hashlib.sha256(result).hexdigest(),
             "callsiteRVA": 0x157EC4, "baselineCall": "e8c77d0000", "stubRVA": stub_rva,
             "controllerRVA": exports["reclaim_controller"] + delta, "stateRVA": state_rva,
             "stateBytes": state_size, "reserveBytes": 256 * 1024**2,
             "exceptionTableRVA": table_rva, "newUnwindEntries": len(new_rows),
             "chainedUnwindRecords": len(chained_records),
             "sections": descriptions, "collectorABI": "unchanged nonmoving Boehm",
             "callSites": [{"rva": site, "originalTarget": old, "stubRVA": stubs[name],
                            "name": name} for site, old, name in sites],
             "exports": {name: value+delta for name, value in exports.items()},
             "stubs": stubs, "thunkUnwindRVA": thunk_unwind_rva,
             "gameCalls": 0, "deploymentRecord": "DEPLOYMENT.json",
             "growthPolicy": "original speculative/fallback batch arguments unchanged",
             "replacesRejectedSHA256": "f3f46bba95a099cf6a20971aa6da0eded497f7b5c71b48653ec35b76bebb310a"}
    (HERE / "PATCH.json").write_text(json.dumps(patch, indent=2) + "\n", encoding="utf-8")
    (HERE / "BUILD.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    command([r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe", "/nologo", "/noconfig",
             "/nostdlib+", "/optimize+", "/target:library", "/out:RetireSample.dll",
             "/reference:" + str(ROOT / "VaM_Data/Managed/mscorlib.dll"), "RetireSample.cs"], records)
    (HERE / "BUILD.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    command([r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe", "/nologo", "/noconfig",
             "/nostdlib+", "/optimize+", "/target:library", "/out:LifecycleSample.dll",
             "/reference:" + str(ROOT / "VaM_Data/Managed/mscorlib.dll"), "LifecycleSample.cs"], records)
    (HERE / "BUILD.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print("BUILD_PASS controller=native-C callsites=5 importsAdded=0 unwind=preserved sections=RX+RW growth=original policies=sort+merge+prefix+retire")


if __name__ == "__main__":
    main()
