"""Verify the installed candidate and read fixed counters only, without game calls."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import struct
import time

from cohort_test import FIRST_FIELDS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main(pid: int) -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    core = runpy.run_path(str(HERE.parent / "mono_unmap_20260930/MODIFIED_FILE.py"))
    reader = core["WindowsReader"](pid)
    started = time.monotonic()
    try:
        base, path = reader.module()
        assert path.resolve() == (ROOT / "Mono/EmbedRuntime/mono.dll").resolve()
        disk = path.read_bytes()
        assert hashlib.sha256(disk).hexdigest() == patch["modifiedSHA256"]
        pe = core["pefile"].PE(data=disk)
        windows = dict(core["SIGNATURE_WINDOWS"])
        for row in patch["callSites"]:
            windows[row["rva"]] = 5
            windows[row["stubRVA"]] = 38
        for edit in patch.get("staticEdits", ()):
            windows[edit["rva"]] = len(bytes.fromhex(edit["modified"]))
        # Verify the entire controller text as well as each native entry.
        code = patch["sections"][0]
        windows[code["rva"]] = code["bytes"]
        for rva, count in windows.items():
            assert reader.read(base + rva, count) == pe.get_data(rva, count)
        fields = FIRST_FIELDS + tuple(patch["extraStateFields"])
        assert len(fields) * 8 == patch["stateBytes"]
        before = core["read_counters"](reader, base)
        raw1 = reader.read(base + patch["stateRVA"], patch["stateBytes"])
        process = reader.process_counters()
        raw2 = reader.read(base + patch["stateRVA"], patch["stateBytes"])
        after = core["read_counters"](reader, base)
        state = dict(zip(fields, struct.unpack(f"<{len(fields)}Q", raw2)))
        assert state["magic"] == 0x31524C5443524347
        accepted = raw1 == raw2 and before == after
        result = dict(pid=pid, utc=datetime.now(timezone.utc).isoformat(), runtimeSHA256=patch["modifiedSHA256"],
            role="current-diagnostic-not-first-ready", codeWindowsVerified=len(windows),
            endpointsEqual=accepted, state=state if accepted else None, counters=before,
            countersEnd=after, process=process, gameCalls=0, gameWrites=0, forcedGC=False,
            elapsedSeconds=time.monotonic()-started, rootAttribution=None, gameBenefitBytes=None)
    finally:
        reader.close()
    (HERE / f"READONLY_{pid}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"READONLY_{'PASS' if accepted else 'REJECTED'} pid={pid} fixedStateWords={len(fields)} writes=0 calls=0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int)
    main(parser.parse_args().pid)
