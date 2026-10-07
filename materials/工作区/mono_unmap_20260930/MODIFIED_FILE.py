# -*- coding: utf-8 -*-
import argparse
import ctypes as C
import ctypes.wintypes as W
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import time

import capstone
import pefile
sys.stdout.reconfigure(encoding="utf-8")

def load(path):
    b = io.open(path, "rb").read()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    coff = pe + 4
    nsec, = struct.unpack_from("<H", b, coff+2)
    optsz, = struct.unpack_from("<H", b, coff+16)
    opt = coff + 20
    magic, = struct.unpack_from("<H", b, opt)
    ddoff = opt + (112 if magic == 0x20b else 96)
    edir_rva, edir_sz = struct.unpack_from("<II", b, ddoff)
    secs = []
    so = opt + optsz
    for i in range(nsec):
        o = so + 40*i
        nm = b[o:o+8].rstrip(b"\0").decode("ascii", "replace")
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", b, o+8)
        secs.append((nm, vaddr, vsize, raddr, rsize))
    def r2o(rva):
        for nm, vaddr, vsize, raddr, rsize in secs:
            if vaddr <= rva < vaddr + max(vsize, rsize):
                return raddr + (rva - vaddr)
        return None
    eo = r2o(edir_rva)
    base       = struct.unpack_from("<I", b, eo+16)[0]
    nfunc      = struct.unpack_from("<I", b, eo+20)[0]
    nnam       = struct.unpack_from("<I", b, eo+24)[0]
    addr_func  = struct.unpack_from("<I", b, eo+28)[0]
    addr_names = struct.unpack_from("<I", b, eo+32)[0]
    names = []
    for i in range(nnam):
        nrva, = struct.unpack_from("<I", b, r2o(addr_names) + 4*i)
        o = r2o(nrva); e = b.index(b"\0", o)
        names.append(b[o:e].decode("ascii", "replace"))
    return b, secs, r2o, base, nfunc, nnam, addr_func, names

MONO = Path(r"F:\vam1.22.0.12\Mono\EmbedRuntime\mono.dll")
MONO_SHA256 = "160f224ead92dac4f33e91a584fdc1c7ef82ed1ced2feac9a903afa31a7e2738"
SUPPORTED_MONO = {
    MONO_SHA256: 6,
    "cd7ab354a43faf18479c3a2d1f57d2d068769b8a490338942f6c510e8b02242d": 1,
}
RVA = {
    "heap": 0x27C7E0, "free": 0x27C808, "unmapped": 0x27EA88,
    "gc_count": 0x269B90, "page_size": 0x26C5C8,
    "free_lists": 0x269D70, "header_index": 0x2BDCD0,
    "zero_index": 0x2BDCC8, "free_marker": 0x269F70,
}
SIGNATURE_WINDOWS = {
    0x158DB4: 16, 0x1B2DC: 8, 0x15EB8C: 194,
    0x15EC50: 191, 0x15EE50: 68, 0x15FC90: 133, 0x1604CD: 26,
}
FREE_LIST_COUNT = 61
BLOCK_SIZE = 4096


def verify_binary(path: Path) -> dict:
    """Bind this private layout to the actual binary, not to a Mono version name."""
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest not in SUPPORTED_MONO:
        raise ValueError("unsupported mono SHA256: " + digest)
    threshold = SUPPORTED_MONO[digest]
    pe = pefile.PE(data=data)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    base = pe.OPTIONAL_HEADER.ImageBase

    def instruction(rva: int):
        return next(md.disasm(pe.get_data(rva, 16), base + rva, count=1))

    def rip_target(rva: int) -> int:
        ins = instruction(rva)
        for op in ins.operands:
            if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                return ins.address + ins.size + op.mem.disp - base
        raise ValueError("missing RIP-relative operand at " + hex(rva))

    checks = {
        "heap getter": rip_target(0x158DB4) == RVA["heap"],
        "free getter": rip_target(0x158DBC) == RVA["free"],
        "collection counter": rip_target(0x1B2DC) == RVA["gc_count"],
        "decommit accounting": rip_target(0x15EC2A) == RVA["unmapped"] and instruction(0x15EC2A).mnemonic == "add",
        "recommit accounting": rip_target(0x15ECF0) == RVA["unmapped"] and instruction(0x15ECF0).mnemonic == "sub",
        "page size": rip_target(0x15EBA0) == RVA["page_size"],
        "header index": rip_target(0x15EE53) == RVA["header_index"],
        "header sentinel": rip_target(0x15EE6C) == RVA["zero_index"],
        "free lists": rip_target(0x15FC9F) == RVA["free_lists"],
        "free list end": rip_target(0x15FCF5) == RVA["free_lists"] + (FREE_LIST_COUNT - 1) * 8,
        "free header marker": rip_target(0x1604DB) == RVA["free_marker"],
        "age condition": instruction(0x15FCC7).mnemonic == "lea" and instruction(0x15FCC7).operands[1].mem.disp == -threshold,
        "MEM_DECOMMIT": instruction(0x15EC01).operands[1].imm == 0x4000,
        "MEM_COMMIT": instruction(0x15ECC6).operands[1].imm == 0x1000,
    }
    imports = {entry.address - base: entry.name for group in pe.DIRECTORY_ENTRY_IMPORT for entry in group.imports}
    checks["VirtualFree"] = imports.get(rip_target(0x15EC14)) == b"VirtualFree"
    checks["VirtualAlloc"] = imports.get(rip_target(0x15ECD9)) == b"VirtualAlloc"
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise ValueError("binary layout mismatch: " + ", ".join(failed))
    return {"sha256": digest, "checks": len(checks), "nativeAgeThreshold": threshold,
            "rva": {name: hex(value) for name, value in RVA.items()}}


def eligible(gc_count: int, reclaimed16: int, threshold: int = 6) -> bool:
    """Exact unsigned predicate at RVA 15FCC3..15FCDB, including 16-bit wrap."""
    cutoff16 = (gc_count - threshold) & 0xFFFF
    return (reclaimed16 > gc_count or reclaimed16 < cutoff16) and cutoff16 < gc_count


def counter_summary(counters: dict[str, int]) -> dict[str, int]:
    heap, free, unmapped = (counters[name] for name in ("heap", "free", "unmapped"))
    if not 0 <= unmapped <= free <= heap < 1 << 44:
        raise ValueError("inconsistent heap/free/unmapped counters")
    return {**counters, "allocatedEstimateBytes": heap - free,
            "committedHeapEstimateBytes": heap - unmapped,
            "committedLargeFreeBytes": free - unmapped}


def read_u64(reader, address: int) -> int:
    return struct.unpack("<Q", reader.read(address, 8))[0]


def read_counters(reader, base: int) -> dict[str, int]:
    return {name: read_u64(reader, base + RVA[name]) for name in ("gc_count", "heap", "free", "unmapped")}


def inventory(reader, base: int, gc_count: int, page_size: int, max_blocks: int = 100000,
              native_age_threshold: int = 6) -> dict:
    """External best-effort walk. Read metadata only; never touch free-block payload."""
    if page_size < BLOCK_SIZE or page_size & (page_size - 1):
        raise ValueError("invalid runtime page size")
    top = struct.unpack("<2048Q", reader.read(base + RVA["header_index"], 2048 * 8))
    sentinel = read_u64(reader, base + RVA["zero_index"])
    free_marker = read_u64(reader, base + RVA["free_marker"])
    heads = reader.read(base + RVA["free_lists"], FREE_LIST_COUNT * 8)
    seen = set()
    result = {"blocks": 0, "freeBytes": 0, "unmappedPageBytes": 0,
              "committedFreeBytes": 0, "eligiblePageBytesAt6": 0,
              "eligiblePageBytesAt2": 0, "eligiblePageBytesNative": 0,
              "nativeAgeThreshold": native_age_threshold, "age16Bytes": {}, "complete": True}

    def header(block: int) -> int:
        key = block >> 22
        node = top[key & 0x7FF]
        for _ in range(4096):
            node_key, next_node = struct.unpack("<QQ", reader.read(node + 0x2010, 16))
            if node_key == key or node == sentinel:
                address = read_u64(reader, node + ((block >> 12) & 0x3FF) * 8)
                if address <= BLOCK_SIZE:
                    raise ValueError("free-list header missing")
                return address
            node = next_node
        raise ValueError("header-index chain limit")

    try:
        # Large/cold buckets first: hot 4KiB nodes are most often reused mid-walk.
        for block in reversed(struct.unpack("<" + "Q" * FREE_LIST_COUNT, heads)):
            while block:
                if len(seen) >= max_blocks:
                    raise ValueError("block limit")
                if block in seen or block % BLOCK_SIZE:
                    raise ValueError("free-list mutation/cycle/alignment")
                seen.add(block)
                header_address = header(block)
                record = reader.read(header_address, 48)
                size, next_block = struct.unpack_from("<QQ", record)
                flags = record[0x29]
                reclaimed = struct.unpack_from("<H", record, 0x2A)[0]
                if struct.unpack_from("<Q", record, 0x20)[0] != free_marker:
                    raise ValueError("free-list node reallocated during walk: " + hex(block))
                if size == 0 or size % BLOCK_SIZE or size >= 1 << 44:
                    raise ValueError("invalid free-block size block=%s header=%s size=%d flags=%d next=%s" % (
                        hex(block), hex(header_address), size, flags, hex(next_block)))
                start = (block + page_size - 1) & -page_size
                end = (block + size) & -page_size
                pages = max(0, end - start)
                result["blocks"] += 1
                result["freeBytes"] += size
                if flags & 2:
                    result["unmappedPageBytes"] += pages
                else:
                    result["committedFreeBytes"] += size
                    age = str((gc_count - reclaimed) & 0xFFFF)
                    result["age16Bytes"][age] = result["age16Bytes"].get(age, 0) + size
                    if eligible(gc_count, reclaimed):
                        result["eligiblePageBytesAt6"] += pages
                    if eligible(gc_count, reclaimed, 2):
                        result["eligiblePageBytesAt2"] += pages
                    if eligible(gc_count, reclaimed, native_age_threshold):
                        result["eligiblePageBytesNative"] += pages
                block = next_block
    except (OSError, ValueError) as error:
        result["complete"] = False
        result["stop"] = str(error)
        result["partialMeaning"] = "observed nodes only; byte totals and eligibility are not a complete allocator inventory"
    result["headsUnchanged"] = heads == reader.read(base + RVA["free_lists"], FREE_LIST_COUNT * 8)
    return result


def snapshot(reader, base: int, max_blocks: int = 100000, scan_blocks: bool = True,
             native_age_threshold: int | None = None) -> dict:
    if native_age_threshold is None:
        native_age_threshold = getattr(reader, "binary", {}).get("nativeAgeThreshold", 6)
    before = read_counters(reader, base)
    counts = counter_summary(before)
    page_size = read_u64(reader, base + RVA["page_size"])
    blocks = inventory(reader, base, before["gc_count"], page_size, max_blocks,
                       native_age_threshold) if scan_blocks else {"requested": False}
    after = read_counters(reader, base)
    stable = before == after
    if scan_blocks:
        stable = (stable and blocks["complete"] and blocks.get("headsUnchanged", False)
                  and blocks["freeBytes"] == before["free"]
                  and blocks["unmappedPageBytes"] == before["unmapped"])
    return {"counters": counts, "inventory": blocks, "consistent": stable,
            "countersConsistent": before == after,
            "consistencyMeaning": ("endpoint counters/heads and byte totals agree" if scan_blocks else "repeated fixed counters agree") + "; not an allocator-locked snapshot",
            "pageSize": page_size, "afterCounters": after}


class ProcessMemoryCounters(C.Structure):
    _fields_ = [("cb", W.DWORD), ("PageFaultCount", W.DWORD)] + [
        (name, C.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
            "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]


class WindowsReader:
    """PROCESS_QUERY_INFORMATION | PROCESS_VM_READ. No writes or injected calls."""
    def __init__(self, pid: int):
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.psapi = C.WinDLL("psapi", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.kernel.OpenProcess.restype = W.HANDLE
        self.kernel.CloseHandle.argtypes = [W.HANDLE]
        self.kernel.CloseHandle.restype = W.BOOL
        self.kernel.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
        self.kernel.ReadProcessMemory.restype = W.BOOL
        self.psapi.EnumProcessModulesEx.argtypes = [W.HANDLE, C.POINTER(W.HMODULE), W.DWORD, C.POINTER(W.DWORD), W.DWORD]
        self.psapi.EnumProcessModulesEx.restype = W.BOOL
        self.psapi.GetModuleFileNameExW.argtypes = [W.HANDLE, W.HMODULE, W.LPWSTR, W.DWORD]
        self.psapi.GetModuleFileNameExW.restype = W.DWORD
        self.psapi.GetProcessMemoryInfo.argtypes = [W.HANDLE, C.POINTER(ProcessMemoryCounters), W.DWORD]
        self.psapi.GetProcessMemoryInfo.restype = W.BOOL
        self.handle = self.kernel.OpenProcess(0x410, False, pid)
        if not self.handle:
            raise C.WinError(C.get_last_error())

    def close(self) -> None:
        self.kernel.CloseHandle(self.handle)

    def read(self, address: int, size: int) -> bytes:
        buffer = C.create_string_buffer(size)
        actual = C.c_size_t()
        if not self.kernel.ReadProcessMemory(self.handle, address, buffer, size, C.byref(actual)) or actual.value != size:
            raise C.WinError(C.get_last_error())
        return buffer.raw

    def module(self) -> tuple[int, Path]:
        modules = (W.HMODULE * 2048)()
        needed = W.DWORD()
        if not self.psapi.EnumProcessModulesEx(self.handle, modules, C.sizeof(modules), C.byref(needed), 3):
            raise C.WinError(C.get_last_error())
        if needed.value > C.sizeof(modules):
            raise ValueError("module-list capacity")
        matches = []
        for address in modules[:needed.value // C.sizeof(W.HMODULE)]:
            name = C.create_unicode_buffer(32768)
            if self.psapi.GetModuleFileNameExW(self.handle, address, name, len(name)) and Path(name.value).name.lower() == "mono.dll":
                matches.append((address, Path(name.value)))
        if len(matches) != 1:
            raise ValueError("expected exactly one loaded mono.dll")
        return matches[0]

    def process_counters(self) -> dict[str, int]:
        counters = ProcessMemoryCounters()
        counters.cb = C.sizeof(counters)
        if not self.psapi.GetProcessMemoryInfo(self.handle, C.byref(counters), counters.cb):
            raise C.WinError(C.get_last_error())
        return {"privateUsageBytes": counters.PrivateUsage, "workingSetBytes": counters.WorkingSetSize}


def live(pid: int, samples: int, interval: float, output: Path | None, scan_blocks: bool = True) -> int:
    reader = WindowsReader(pid)
    try:
        base, path = reader.module()
        binary = verify_binary(path)
        pe = pefile.PE(str(path))
        for rva, size in SIGNATURE_WINDOWS.items():
            if reader.read(base + rva, size) != pe.get_data(rva, size):
                raise ValueError("runtime code signature mismatch at " + hex(rva))
        report = {"pid": pid, "module": str(path), "moduleBase": hex(base),
                  "binary": binary, "remoteWrites": 0, "callsIntoGame": 0, "samples": []}
        for n in range(samples):
            started = time.monotonic()
            sample = snapshot(reader, base, scan_blocks=scan_blocks,
                              native_age_threshold=binary["nativeAgeThreshold"])
            sample["process"] = reader.process_counters()
            sample["timeUTC"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            sample["elapsedMs"] = round((time.monotonic() - started) * 1000, 1)
            report["samples"].append(sample)
            c, b = sample["counters"], sample["inventory"]
            print("SAMPLE n=%d gc=%d heapMiB=%.2f freeMiB=%.2f unmappedMiB=%.2f committedFreeMiB=%.2f consistent=%s" % (
                n + 1, c["gc_count"], c["heap"] / 2**20, c["free"] / 2**20, c["unmapped"] / 2**20,
                c["committedLargeFreeBytes"] / 2**20, sample["consistent"]))
            if scan_blocks:
                print("INVENTORY blocks=%d freeMiB=%.2f unmappedMiB=%.2f eligible6MiB=%.2f eligible2MiB=%.2f nativeAge=%d eligibleNativeMiB=%.2f complete=%s stop=%s" % (
                    b["blocks"], b["freeBytes"] / 2**20, b["unmappedPageBytes"] / 2**20,
                    b["eligiblePageBytesAt6"] / 2**20, b["eligiblePageBytesAt2"] / 2**20,
                    b["nativeAgeThreshold"], b["eligiblePageBytesNative"] / 2**20,
                    b["complete"], b.get("stop", "none")))
            if n + 1 < samples:
                time.sleep(interval)
        if output:
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        complete = all(sample["consistent"] for sample in report["samples"])
        print("LIVE_%s samples=%d writes=0 callsIntoGame=0 output=%s" % ("PASS" if complete else "PARTIAL", samples, output))
        return 0 if complete else 2
    finally:
        reader.close()


def exports(path: Path) -> None:
    _, _, _, base, nfunc, nnam, _, names = load(str(path))
    print("== mono.dll : %d named exports, base=%d, nfunc=%d ==" % (nnam, base, nfunc))
    g = sorted(set(s for s in names if s.startswith("mono_gc")))
    print("\n-- mono_gc_* exports (%d) --" % len(g))
    for name in g:
        print("   " + name)
    print("\n-- heap walk / dump / stat / profiler related (any prefix) --")
    keys = ("walk", "dump", "heap", "snapshot", "iterate", "foreach", "class_get", "prof")
    for name in sorted(set(name for name in names if any(key in name.lower() for key in keys))):
        print("   " + name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only, binary-bound Boehm unmap sampler")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--counters-only", action="store_true",
                        help="read fixed counters without traversing concurrently reused free lists")
    args = parser.parse_args()
    if args.verify:
        result = verify_binary(MONO)
        print("VERIFY_PASS checks=%d nativeAgeThreshold=%d sha256=%s" % (
            result["checks"], result["nativeAgeThreshold"], result["sha256"]))
        return 0
    if args.live:
        if not args.pid or not 1 <= args.samples <= 20 or not 0 <= args.interval <= 60:
            parser.error("live mode requires --pid > 0, --samples 1..20 and --interval 0..60")
        return live(args.pid, args.samples, args.interval, args.output, not args.counters_only)
    exports(MONO)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print("PROBE_ERROR: " + str(error), file=sys.stderr)
        raise SystemExit(1)
