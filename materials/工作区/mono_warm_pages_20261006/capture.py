"""Read only verified code windows and fixed native counters; no heap/pixel scan."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import struct
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LEGACY = HERE.parent / "mono_allocator_lifecycle_20261006"
sys.path.insert(0, str(LEGACY))
from sample import FIELDS


def main(pid: int) -> None:
    patch = json.loads((LEGACY / "PATCH.json").read_text(encoding="utf-8"))
    core = runpy.run_path(str(LEGACY.parent / "mono_unmap_20260930/MODIFIED_FILE.py"))
    reader = core["WindowsReader"](pid)
    started = time.monotonic()
    try:
        base, path = reader.module()
        assert path.resolve() == (ROOT / "Mono/EmbedRuntime/mono.dll").resolve()
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        assert sha == patch["modifiedSHA256"]
        pe = core["pefile"].PE(str(path))
        windows = dict(core["SIGNATURE_WINDOWS"])
        for row in patch["callSites"]:
            windows[row["rva"]] = 5
            windows[row["stubRVA"]] = 38
        for rva, count in windows.items():
            assert reader.read(base + rva, count) == pe.get_data(rva, count)
        before = core["read_counters"](reader, base)
        state = dict(zip(FIELDS, struct.unpack("<29Q", reader.read(base + patch["stateRVA"], 232))))
        assert state["magic"] == 0x31524C5443524347
        process = reader.process_counters()
        after = core["read_counters"](reader, base)
        result = dict(pid=pid, utc=datetime.now(timezone.utc).isoformat(),
            role="diagnostic-current-not-first-ready", runtimeSHA256=sha,
            codeWindowsVerified=len(windows), counters=before, countersEnd=after,
            countersEqual=before == after, state=state, process=process,
            gameCalls=0, gameWrites=0, forcedGC=False, payloadBytesRead=0)
    finally:
        reader.close()
    result["captureSeconds"] = time.monotonic() - started
    traces = sorted((ROOT / "BepInEx/config").glob("Quest3TriggerUI.charactertrace_20261006_1402*.tsv"))
    events = []
    for trace in traces:
        for line in trace.read_text(encoding="utf-8-sig").splitlines():
            columns = line.split("\t")
            if len(columns) >= 6 and columns[4] in ("gc", "END"):
                events.append(dict(file=str(trace.relative_to(ROOT)), line=line))
    result["existingTraceEvents"] = events
    result["interpretation"] = (
        "Native cumulative counts are activity, not elapsed GC subphase time or current bytes. "
        "rejected includes policy admission rejection without a reason code. "
        "GC trace timings cover the complete invoked GC, not proof of sorter cost. "
        "This current/idle point is not a first-ready memory-growth comparison.")
    (HERE / "READONLY.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"READONLY_PASS pid={pid} codeWindows={len(windows)} "
          f"nativeGC={before['gc_count']} sortRejected={state['rejected']} "
          f"writes=0 calls=0 firstReady=False")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int)
    main(parser.parse_args().pid)
