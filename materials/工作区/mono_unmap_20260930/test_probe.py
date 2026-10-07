import argparse
import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
MONO = Path(r"F:\vam1.22.0.12\Mono\EmbedRuntime\mono.dll")
SHA = "160f224ead92dac4f33e91a584fdc1c7ef82ed1ced2feac9a903afa31a7e2738"
probe = None


class Capture(io.StringIO):
    def reconfigure(self, **kwargs) -> None:
        pass


def import_probe(path: Path):
    spec = importlib.util.spec_from_file_location("probe_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(Capture()):
        spec.loader.exec_module(module)
    return module


class BaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loaded = probe.load(str(MONO))

    def test_binary_identity(self) -> None:
        self.assertEqual(hashlib.sha256(self.loaded[0]).hexdigest(), SHA)

    def test_export_count(self) -> None:
        self.assertEqual(self.loaded[5], 806)
        self.assertEqual(len(self.loaded[7]), 806)

    def test_export_table_base(self) -> None:
        self.assertEqual(self.loaded[3:5], (1, 806))

    def test_gc_exports(self) -> None:
        names = self.loaded[7]
        self.assertIn("mono_gc_get_heap_size", names)
        self.assertIn("mono_gc_get_used_size", names)
        self.assertFalse(any(name.startswith("GC_") for name in names))

    def test_section_conversion(self) -> None:
        data, _, convert, *_ = self.loaded
        self.assertEqual(data[convert(0x15FCC7):convert(0x15FCC7) + 3], bytes.fromhex("8d41fa"))

    def test_original_export_output(self) -> None:
        capture = Capture()
        spec = importlib.util.spec_from_file_location("original_export_probe", ROOT / "BASELINE.py")
        original = importlib.util.module_from_spec(spec)
        with contextlib.redirect_stdout(capture):
            spec.loader.exec_module(original)
        if hasattr(probe, "exports"):
            other = Capture()
            with contextlib.redirect_stdout(other):
                probe.exports(MONO)
            self.assertEqual(other.getvalue(), capture.getvalue())
        else:
            self.assertIn("806 named exports", capture.getvalue())


class MemoryImage:
    def __init__(self) -> None:
        self.segments = {}
        self.gc_reads = 0
        self.change_gc = False

    def add(self, address: int, data: bytes) -> None:
        self.segments[address] = data

    def read(self, address: int, size: int) -> bytes:
        if address == probe.RVA["gc_count"]:
            self.gc_reads += 1
            if self.change_gc and self.gc_reads > 1:
                return struct.pack("<Q", 21)
        for start, data in self.segments.items():
            if start <= address and address + size <= start + len(data):
                return data[address - start:address - start + size]
        raise OSError("fixture missing address " + hex(address))


def fixture() -> MemoryImage:
    image = MemoryImage()
    for name, value in {"gc_count": 20, "heap": 65536, "free": 16384,
                        "unmapped": 4096, "page_size": 4096, "free_marker": 0xDEADBEEF}.items():
        image.add(probe.RVA[name], struct.pack("<Q", value))
    top = bytearray(2048 * 8)
    node, sentinel = 0x1000000, 0x1003000
    struct.pack_into("<Q", top, 8, node)
    image.add(probe.RVA["header_index"], bytes(top))
    image.add(probe.RVA["zero_index"], struct.pack("<Q", sentinel))
    heads = bytearray(probe.FREE_LIST_COUNT * 8)
    struct.pack_into("<Q", heads, 0, 0x400000)
    image.add(probe.RVA["free_lists"], bytes(heads))
    bottom = bytearray(0x2020)
    struct.pack_into("<QQ", bottom, 0x2010, 1, sentinel)
    records = [(0x400000, 4096, 0x401000, 0, 13),
               (0x401000, 8192, 0x403000, 0, 17),
               (0x403000, 4096, 0, 2, 12)]
    for index, (block, size, next_block, flags, reclaimed) in enumerate(records):
        address = 0x1200000 + index * 0x100
        struct.pack_into("<Q", bottom, ((block >> 12) & 0x3FF) * 8, address)
        header = bytearray(48)
        struct.pack_into("<QQ", header, 0, size, next_block)
        header[0x29] = flags
        struct.pack_into("<Q", header, 0x20, 0xDEADBEEF)
        struct.pack_into("<H", header, 0x2A, reclaimed)
        image.add(address, bytes(header))
    image.add(node, bytes(bottom))
    return image


class UnmapTests(unittest.TestCase):
    def test_static_layout(self) -> None:
        result = probe.verify_binary(MONO)
        self.assertEqual(result["checks"], 16)
        self.assertEqual(result["nativeAgeThreshold"], 6)

    def test_unknown_binary(self) -> None:
        with patch.object(Path, "read_bytes", return_value=b"different mono"):
            with self.assertRaisesRegex(ValueError, "unsupported mono SHA256"):
                probe.verify_binary(MONO)

    def test_age_boundary(self) -> None:
        self.assertTrue(probe.eligible(20, 13))
        self.assertFalse(probe.eligible(20, 14))
        self.assertFalse(probe.eligible(20, 20))
        self.assertTrue(probe.eligible(20, 17, 2))
        self.assertFalse(probe.eligible(20, 18, 2))

    def test_age_underflow_and_native_wrap(self) -> None:
        self.assertFalse(probe.eligible(3, 0))
        self.assertFalse(probe.eligible(6, 0))
        self.assertTrue(probe.eligible(7, 0))
        self.assertTrue(probe.eligible(100, 65530))
        self.assertFalse(probe.eligible(65540, 65534))

    def test_decommit_does_not_shrink_logical_heap(self) -> None:
        before = probe.counter_summary({"heap": 100, "free": 40, "unmapped": 10})
        after = probe.counter_summary({"heap": 100, "free": 40, "unmapped": 30})
        self.assertEqual(before["heap"], after["heap"])
        self.assertEqual(before["committedLargeFreeBytes"] - after["committedLargeFreeBytes"], 20)

    def test_invalid_counters(self) -> None:
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            probe.counter_summary({"heap": 10, "free": 11, "unmapped": 0})
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            probe.counter_summary({"heap": 10, "free": 8, "unmapped": 9})

    def test_free_list_inventory(self) -> None:
        result = probe.snapshot(fixture(), 0)
        self.assertTrue(result["consistent"])
        self.assertEqual(result["counters"]["committedLargeFreeBytes"], 12288)
        self.assertEqual(result["inventory"]["unmappedPageBytes"], 4096)
        self.assertEqual(result["inventory"]["eligiblePageBytesAt6"], 4096)
        self.assertEqual(result["inventory"]["eligiblePageBytesAt2"], 12288)
        self.assertEqual(result["inventory"]["age16Bytes"], {"7": 4096, "3": 8192})

    def test_capped_inventory(self) -> None:
        result = probe.snapshot(fixture(), 0, max_blocks=1)
        self.assertFalse(result["consistent"])
        self.assertFalse(result["inventory"]["complete"])
        self.assertEqual(result["inventory"]["stop"], "block limit")

    def test_gc_race_not_called_consistent(self) -> None:
        image = fixture()
        image.change_gc = True
        result = probe.snapshot(image, 0)
        self.assertFalse(result["consistent"])
        self.assertEqual(result["afterCounters"]["gc_count"], 21)

    def test_free_list_cycle_is_visible_partial(self) -> None:
        image = fixture()
        header = bytearray(image.segments[0x1200200])
        struct.pack_into("<Q", header, 8, 0x400000)
        image.segments[0x1200200] = bytes(header)
        result = probe.snapshot(image, 0)
        self.assertFalse(result["consistent"])
        self.assertFalse(result["inventory"]["complete"])
        self.assertIn("mutation/cycle/alignment", result["inventory"]["stop"])

    def test_reallocated_header_is_visible_partial(self) -> None:
        image = fixture()
        header = bytearray(image.segments[0x1200000])
        struct.pack_into("<Q", header, 0x20, 123)
        image.segments[0x1200000] = bytes(header)
        result = probe.snapshot(image, 0)
        self.assertFalse(result["consistent"])
        self.assertIn("reallocated during walk", result["inventory"]["stop"])

    def test_counters_only_keeps_decommit_accounting(self) -> None:
        result = probe.snapshot(fixture(), 0, scan_blocks=False)
        self.assertTrue(result["consistent"])
        self.assertEqual(result["counters"]["committedLargeFreeBytes"], 12288)
        self.assertEqual(result["inventory"], {"requested": False})


def main() -> int:
    global probe
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("BASELINE", "MODIFIED", "ROLLBACK"))
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    source = args.source or ROOT / ("MODIFIED_FILE.py" if args.stage == "MODIFIED" else "BASELINE.py")
    probe = import_probe(source)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BaselineTests)
    if args.stage == "MODIFIED":
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(UnmapTests))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    if not result.wasSuccessful():
        print(stream.getvalue())
        return 1
    print("%s_PASS tests=%d namedExports=806 source=%s" % (args.stage, result.testsRun, source.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
