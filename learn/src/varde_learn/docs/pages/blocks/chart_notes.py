"""Validation of chart notes: point markers and bands, with tone."""

import math

from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    is_number,
    str_field,
    tables,
    tables_fault,
)

MAX_NOTES = 12
TONES = ("info", "decision", "risk", "warning", "success")


def _finite(value: object) -> bool:
    return is_number(value) and math.isfinite(value)  # type: ignore[arg-type]


def _tone_faults(note: dict[str, object], where: str) -> list[Fault]:
    if "tone" not in note or note["tone"] in TONES:
        return []
    return [Fault("note-tone", f"{where}.tone must be one of {list(TONES)}")]


def _point_fault(data: dict[str, object], value: object, where: str) -> Fault | None:
    labels = data.get("labels")
    if data.get("kind") == "scatter":
        ok = _finite(value)
        return None if ok else Fault("note-x", f"{where} must be a number")
    ok = isinstance(labels, list) and isinstance(value, str) and value in labels
    return None if ok else Fault("note-x", f"{where} must be one of the labels")


def _scatter_span(data: dict[str, object]) -> tuple[float, float] | None:
    xs = [
        x
        for s in tables(data, "series", "chart")
        for x in (s.get("x") if isinstance(s.get("x"), list) else [])  # type: ignore[union-attr]
        if _finite(x)
    ]
    return (min(xs), max(xs)) if xs else None  # type: ignore[type-var]


def _range_faults(
    data: dict[str, object], note: dict[str, object], where: str
) -> list[Fault]:
    start, end = note["from"], note["to"]
    if data.get("kind") == "scatter":
        if not (_finite(start) and _finite(end)):
            return []
        if start >= end:  # type: ignore[operator]
            return [Fault("note-range", f"{where}: from must be less than to")]
        span = _scatter_span(data)
        if span and not (span[0] <= start and end <= span[1]):  # type: ignore[operator]
            return [Fault("note-range", f"{where}: from and to must lie in the data")]
        return []
    labels = data.get("labels")
    if not isinstance(labels, list) or start not in labels or end not in labels:
        return []
    if labels.index(start) > labels.index(end):
        return [Fault("note-range", f"{where}: from must not come after to")]
    return []


def _marker_faults(
    data: dict[str, object], note: dict[str, object], where: str
) -> list[Fault]:
    faults = check_keys(note, {"x", "label"}, {"tone"}, where)
    fault = _point_fault(data, note["x"], f"{where}.x") if "x" in note else None
    return faults + ([fault] if fault else [])


def _band_faults(
    data: dict[str, object], note: dict[str, object], where: str
) -> list[Fault]:
    faults = check_keys(note, {"from", "to", "label"}, {"tone"}, where)
    ends = [
        (key, _point_fault(data, note[key], f"{where}.{key}"))
        for key in ("from", "to")
        if key in note
    ]
    faults += [fault for _, fault in ends if fault]
    if len(ends) == 2 and not any(fault for _, fault in ends):
        faults += _range_faults(data, note, where)
    return faults


def _note_faults_one(
    data: dict[str, object], note: dict[str, object], where: str
) -> list[Fault]:
    if "x" in note and ("from" in note or "to" in note):
        return [Fault("note-mixed", f"{where}: x cannot be combined with from or to")]
    body = _marker_faults if "x" in note else _band_faults
    return (
        str_field(note, "label", where)
        + _tone_faults(note, where)
        + body(data, note, where)
    )


def note_faults(data: dict[str, object]) -> list[Fault]:
    if "notes" not in data:
        return []
    faults = tables_fault(data, "notes", "chart")
    notes = tables(data, "notes", "chart")
    if len(notes) > MAX_NOTES:
        faults.append(Fault("too-many", f"chart.notes: at most {MAX_NOTES} notes"))
    for n, note in enumerate(notes, 1):
        faults += _note_faults_one(data, note, f"notes[{n}]")
    return faults
