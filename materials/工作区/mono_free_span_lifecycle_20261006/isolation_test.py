"""Fault injection in a private real-Mono runtime, restored before it resumes."""
from __future__ import annotations

import ctypes as C
import hashlib
import json
from pathlib import Path
import sys

from cohort_test import FIRST_FIELDS, Report

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main(mode: str) -> None:
    patch = json.loads((HERE / "PATCH.json").read_text(encoding="utf-8"))
    baseline_patch = json.loads((HERE.parent / "mono_reclaim_cohorts_20261006/PATCH.json").read_text(encoding="utf-8"))
    name = {"BASELINE": "BASELINE.dll", "MODIFIED": "MODIFIED_FILE.dll", "ROLLBACK": "rollback_copy/mono.dll"}[mode]
    expected = patch["modifiedSHA256" if mode == "MODIFIED" else "baselineSHA256"]
    assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == expected
    mono = C.CDLL(str(HERE / name))
    ptr, string = C.c_void_p, C.c_char_p

    def api(name: str, result, *args):
        f = getattr(mono, name)
        f.restype, f.argtypes = result, list(args)
        return f

    api("mono_set_assemblies_path", None, string)((str(HERE) + ";" + str(ROOT / "VaM_Data/Managed")).encode())
    api("mono_set_dirs", None, string, string)(str(ROOT / "VaM_Data/Managed").encode(), str(ROOT / "Mono/etc").encode())
    domain = api("mono_jit_init_version", ptr, string, string)(b"ChainIsolation", b"v2.0.50727")
    assembly = api("mono_domain_assembly_open", ptr, ptr, string)(domain, str(HERE / "PendingCohort.dll").encode())
    assert domain and assembly
    image = api("mono_assembly_get_image", ptr, ptr)(assembly)
    klass = api("mono_class_from_name", ptr, ptr, string, string)
    method = api("mono_class_get_method_from_name", ptr, ptr, string, C.c_int)
    invoke = api("mono_runtime_invoke", ptr, ptr, ptr, ptr, C.POINTER(ptr))

    def action(type_name: str, name: str) -> None:
        k = klass(image, b"", type_name.encode())
        f = method(k, name.encode(), 0)
        assert f
        error = ptr()
        assert invoke(f, None, None, C.byref(error)) and not error.value, name

    action("LifecycleSample", "PrepareCells")
    action("PendingCohort", "PrepareOther")
    action("LifecycleSample", "DropCells")
    action("PendingCohort", "DropOther")
    api("mono_gc_collect", None, C.c_int)(0)
    find = C.CFUNCTYPE(ptr, C.c_uint64)(mono._handle + 0x15EE50)
    probe = C.CDLL(str(HERE / "pending_probe.dll")).pending_probe
    probe.argtypes, probe.restype = (ptr, C.POINTER(Report)), None

    def word(address: int):
        return C.c_uint64.from_address(address)

    def chain(kind: int, size: int) -> tuple[int, list[int]]:
        pending = word(mono._handle + 0x2659A0 + kind * 32 + 8).value
        slot = pending + size * 8
        block, pages, seen = word(slot).value, [], set()
        while block:
            assert len(pages) < 32768 and block not in seen
            pages.append(block)
            seen.add(block)
            block = word(find(block) + 8).value
        return slot, pages

    slot, targets = chain(0, 4)
    other_slot, other = chain(0, 6)
    assert len(targets) > 1000 and len(other) > 1000
    disable = C.CFUNCTYPE(None)(mono._handle + 0x158EB8)
    enable = C.CFUNCTYPE(None)(mono._handle + 0x158E8C)
    used_patch = patch if mode == "MODIFIED" else baseline_patch
    state_rva = used_patch["stateRVA"]
    previous_fields = baseline_patch["extraStateFields"]
    fields = FIRST_FIELDS + tuple(patch["extraStateFields"]) if mode == "MODIFIED" else FIRST_FIELDS + tuple(previous_fields)

    def state() -> dict:
        return dict(zip(fields, (C.c_uint64 * len(fields)).from_address(mono._handle + state_rva)))

    controller = C.CFUNCTYPE(None, ptr, ptr)(mono._handle + used_patch["exports"]["reclaim_controller"])
    evidence = []
    # Each failure is local to (kind0,size4); same-kind size6 must remain serviced.
    for fault in ("size", "marks", "cycle"):
        slot, targets = chain(0, 4)
        other_slot, other = chain(0, 6)
        assert len(targets) > 1000 and len(other) > 1000
        original = {block: word(find(block) + 8).value for block in targets + other}
        original_target_head, original_other_head = word(slot).value, word(other_slot).value
        h = find(targets[0])
        original_size = word(h).value
        original_marks = [word(h + 48 + i * 8).value for i in range(8)]
        before = state()
        disable()
        try:
            # Reverse the independently valid queue, creating known disorder.
            for block, successor in zip(other, [0] + other[:-1]):
                word(find(block) + 8).value = successor
            word(other_slot).value = other[-1]
            if fault == "size":
                word(h).value = original_size + 1
            elif fault == "marks":
                for i in range(8): word(h + 48 + i * 8).value = 0xffffffffffffffff
            else:
                word(h + 8).value = targets[0]
            corrupted_next = word(h + 8).value
            controller(mono._handle, mono._handle + state_rva)
            after = state()
            assert word(slot).value == original_target_head and word(h + 8).value == corrupted_next
            assert all(word(find(block) + 8).value == (corrupted_next if block == targets[0] else original[block])
                       for block in targets)
            valid_slot, valid_after = chain(0, 6)
            assert valid_slot == other_slot and set(valid_after) == set(other)
            report = Report()
            if fault != "cycle":
                probe(mono._handle, C.byref(report))
                row = next(r for r in report.chain[:report.chains] if r.kind == 0 and r.size == 6)
                inversions = row.inversions
            else:
                # Do not ask the full probe to traverse an intentionally cyclic chain.
                bands = []
                for block in valid_after:
                    hdr = find(block)
                    marks = sum(word(hdr + 48 + 8*i).value.bit_count() for i in range(8))
                    bands.append(min(7, marks * 8 // (512 // 6)))
                inversions = sum(a < b for a, b in zip(bands, bands[1:]))
            assert inversions == 0
            assert after["lastRejectReason"] == {"size": 4, "marks": 7, "cycle": 1}[fault]
            evidence.append(dict(fault=fault, unrelatedInversions=inversions, before=before, after=after,
                                 rejectedChainUnchanged=True, unrelatedMembersUnchanged=True))
        finally:
            word(h).value = original_size
            for i, value in enumerate(original_marks): word(h + 48 + i * 8).value = value
            for block, successor in original.items(): word(find(block) + 8).value = successor
            word(slot).value = original_target_head
            word(other_slot).value = original_other_head
            enable()
        action("LifecycleSample", "CheckCells")
        action("PendingCohort", "CheckOther")
    action("LifecycleSample", "DropCellRoots")
    action("PendingCohort", "ReleaseOther")
    api("mono_gc_collect", None, C.c_int)(0)
    (HERE / (mode + "_ISOLATION.json")).write_text(json.dumps(dict(mode=mode, runtimeSHA256=expected,
        rows=evidence, restoredBeforeRuntimeResume=True, gameWrites=0, gameCalls=0), indent=2) + "\n", encoding="utf-8")
    print(f"ISOLATION_PASS mode={mode} faults=size+marks+cycle invalidChain=unchanged unrelatedChain="
          "sorted nativeState=restored gameCalls=0 gameWrites=0")


if __name__ == "__main__":
    main(sys.argv[1])
