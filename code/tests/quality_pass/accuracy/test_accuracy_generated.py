"""A19: generated/vendored detection on hand-labelled fixture files.

Ground truth in ``fixtures/accuracy/labels/generated.json`` says whether each
fixture really is generator output or a third-party copy; the set composition,
the per-file evidence and the limitations of the set are described in
``fixtures/accuracy/README.md``.

Two measurements use the same labels:

* raw detection (the A19 threshold applies to this one): the engine's file
  markers, the path classification by directory convention, or the minified
  exclusion;
* the gate-mode exclusion decision (``gate_mode=True``, no base-ref allowlist
  and no extra generator signature), where a marker alone does not exclude.
"""

from __future__ import annotations

from collections import defaultdict
from functools import cache
from typing import SupportsIndex, overload

from accuracy_audit import generated_signals, labels, record_rate
from varde_code.parse import parse_source_for_path
from varde_code.quality_pass import facts as facts_module
from varde_code.quality_pass.facts import extract_facts

GENERATED_LABELS = labels("generated.json")
POSITIVE_LABELS = {"generated", "vendored"}
RECALL_THRESHOLD = 0.95
PRECISION_THRESHOLD = 0.98

# The fixed header markers do not flag prose in hand-written negatives.
RECORDED_FALSE_POSITIVES = ()
RECORDED_RAW_COUNTS = {"tp": 82, "fp": 0, "fn": 0, "tn": 53}
RECORDED_GATE_COUNTS = {"tp": 41, "fp": 0, "fn": 41, "tn": 53}


@cache
def _evaluate() -> dict:
    raw = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    gate = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    false_positives: list[str] = []
    false_negatives: list[str] = []
    signal_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for relative_path, metadata in sorted(GENERATED_LABELS.items()):
        signals = generated_signals(relative_path)
        positive = metadata["label"] in POSITIVE_LABELS
        if positive:
            signal_counts[metadata["signal"]][1] += 1
        if positive and signals.raw:
            raw["tp"] += 1
            signal_counts[metadata["signal"]][0] += 1
        elif positive:
            raw["fn"] += 1
            false_negatives.append(relative_path)
        elif signals.raw:
            raw["fp"] += 1
            false_positives.append(relative_path)
        else:
            raw["tn"] += 1
        if positive and signals.gate:
            gate["tp"] += 1
        elif positive:
            gate["fn"] += 1
        elif signals.gate:
            gate["fp"] += 1
        else:
            gate["tn"] += 1
    return {
        "raw": raw,
        "gate": gate,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "signals": {
            name: tuple(value) for name, value in sorted(signal_counts.items())
        },
    }


def _rate_lines() -> list[str]:
    result = _evaluate()
    lines = []
    for name in ("raw", "gate"):
        counts = result[name]
        positives = counts["tp"] + counts["fn"]
        predicted = counts["tp"] + counts["fp"]
        lines.append(
            f"{name}: positives={positives} negatives={counts['tn'] + counts['fp']} "
            f"tp={counts['tp']} fp={counts['fp']} fn={counts['fn']} tn={counts['tn']} "
            f"recall={counts['tp'] / positives:.2%} "
            f"precision={counts['tp'] / predicted:.2%}"
        )
    lines.extend(
        f"signal {name}: {detected}/{total} detected"
        for name, (detected, total) in result["signals"].items()
    )
    lines.extend(f"false positive: {path}" for path in result["false_positives"])
    lines.extend(f"false negative: {path}" for path in result["false_negatives"])
    return lines


def _report() -> dict:
    lines = _rate_lines()
    record_rate("A19 generated/vendored", *lines)
    print("A19 " + "\nA19 ".join(lines))
    return _evaluate()


def test_a19_raw_recall_is_at_least_95_percent():
    counts = _report()["raw"]
    positives = counts["tp"] + counts["fn"]

    assert counts["tp"] / positives >= RECALL_THRESHOLD


def test_a19_raw_precision_is_at_least_98_percent():
    counts = _report()["raw"]
    predicted = counts["tp"] + counts["fp"]

    assert counts["tp"] / predicted >= PRECISION_THRESHOLD


def test_a19_raw_counts_and_false_positives_are_the_recorded_set():
    result = _report()
    print("A19 computed false positives: " + ", ".join(result["false_positives"]))

    assert result["raw"] == RECORDED_RAW_COUNTS
    assert tuple(result["false_positives"]) == RECORDED_FALSE_POSITIVES


def test_a19_gate_mode_counts_are_the_recorded_set():
    """State the gate-mode decision on the same labels.

    The A19 threshold applies to the raw detection signal; gate mode with no
    base-ref allowlist excludes only path conventions and minified files, so
    marker-only positives are not excluded there.
    """
    assert _report()["gate"] == RECORDED_GATE_COUNTS


def test_a19_marker_detection_requires_a_header_notice_phrase():
    header_prose = extract_facts(
        "// The generated id is checked; this cache was regenerated and not "
        "degenerated.\n"
        "int value() { return 1; }\n",
        "cpp",
        "src/value.cpp",
    )
    late_notice = extract_facts(
        "int value() { return 1; }\n// Code generated by a local script.\n",
        "cpp",
        "src/value.cpp",
    )
    header_notice = extract_facts(
        "// Code generated by a local script.\nint value() { return 1; }\n",
        "cpp",
        "src/value.cpp",
    )

    assert header_prose["markers"] == []
    assert late_notice["markers"] == []
    assert header_notice["markers"] == ["generated"]


def test_a19_marker_scan_work_is_linear_for_ten_thousand_comments():
    class CountingBytes(bytes):
        examined = 0

        @overload
        def __getitem__(self, key: SupportsIndex) -> int: ...

        @overload
        def __getitem__(self, key: slice) -> bytes: ...

        def __getitem__(self, key: SupportsIndex | slice) -> int | bytes:
            if isinstance(key, slice):
                self.examined += len(range(*key.indices(len(self))))
            return super().__getitem__(key)

    plain = "\n".join(f"// note {index}" for index in range(10_000))
    plain += "\nint value() { return 1; }\n"
    source = CountingBytes(plain.encode())
    root = parse_source_for_path("cpp", "many-comments.cpp", plain).root

    work = {}
    assert facts_module._markers(root, source, work) == []
    assert work["comment_lines"] == 10_000
    assert source.examined <= len(source) * 3
