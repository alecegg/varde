"""Block type for a source file with notes anchored to line ranges: annotated-code."""

import re

from varde_learn.docs.pages.blocks.rules import Fault, check_keys, str_field
from varde_learn.docs.pages.blocks.spec import BlockSpec

KINDS = ("info", "warn", "change")
MAX_NOTES = 40
MAX_NOTES_PER_LINE = 6
_RANGE = re.compile(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*")


def source_line_count(source: str) -> int:
    """Lines the code panel shows for this source (a closing newline adds none)."""
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return len(lines) - 1 if len(lines) > 1 and not lines[-1] else len(lines)


def parse_range(value: object) -> tuple[int, int] | None:
    """`5`, `"5"` or `"5-6"` as (from, to); None when it is not a valid range."""
    if isinstance(value, bool):
        return None
    text = str(value) if isinstance(value, int) else value
    match = _RANGE.fullmatch(text) if isinstance(text, str) else None
    if not match:
        return None
    low = int(match[1])
    high = int(match[2] or low)
    return (low, high) if 1 <= low <= high else None


def _note_faults(note: object, where: str, total: int) -> list[Fault]:
    if not isinstance(note, dict):
        return [Fault("type", f"{where} must be a table")]
    faults = check_keys(note, {"lines", "note"}, {"label", "kind"}, where)
    for key in ("note", "label"):
        faults += str_field(note, key, where)
    if "kind" in note and note["kind"] not in KINDS:
        faults.append(Fault("type", f"{where}: kind must be one of {', '.join(KINDS)}"))
    if "lines" not in note:
        return faults
    span = parse_range(note["lines"])
    if span is None:
        return faults + [Fault("type", f"{where}: lines must be n or 'from-to'")]
    if span[1] > total:
        faults.append(
            Fault("range", f"{where}: lines {span[0]}-{span[1]} pass line {total}")
        )
    return faults


def _crowded_faults(notes: list[object]) -> list[Fault]:
    starts: dict[int, int] = {}
    for note in notes:
        span = parse_range(note.get("lines")) if isinstance(note, dict) else None
        if span:
            starts[span[0]] = starts.get(span[0], 0) + 1
    return [
        Fault(
            "limit",
            f"annotated-code: more than {MAX_NOTES_PER_LINE} notes start at line {n}",
        )
        for n, count in sorted(starts.items())
        if count > MAX_NOTES_PER_LINE
    ]


def _notes_faults(data: dict[str, object]) -> list[Fault]:
    notes = data.get("notes")
    if not isinstance(notes, list):
        return [Fault("type", "annotated-code: 'notes' must be a list of tables")]
    faults: list[Fault] = []
    if len(notes) > MAX_NOTES:
        faults.append(Fault("limit", f"annotated-code: at most {MAX_NOTES} notes"))
    source = data.get("source")
    total = source_line_count(source) if isinstance(source, str) else 0
    for i, note in enumerate(notes, 1):
        faults += _note_faults(note, f"annotated-code: notes[{i}]", total)
    return faults + _crowded_faults(notes)


def validate_annotated_code(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(
        data,
        {"filename", "language", "source", "notes"},
        {"collapse"},
        "annotated-code",
    )
    for key in ("filename", "language", "source"):
        faults += str_field(data, key, "annotated-code")
    if "collapse" in data and not isinstance(data["collapse"], bool):
        faults.append(Fault("type", "annotated-code: 'collapse' must be true or false"))
    return faults + (_notes_faults(data) if "notes" in data else [])


ANNOTATED_CODE = BlockSpec(
    "annotated-code",
    "A source file with notes on line ranges; quiet stretches fold away",
    (
        "filename  file name shown in the header",
        "language  python, js, ts, json or shell are highlighted; others show plain",
        "source    the code, as one string",
        "notes     list of {lines, note, label, kind}, up to 40; lines is n or 'a-b'",
        "          inside the source; kind is info (default), warn or change",
        "collapse  optional false: show every line (default folds stretches of 4 or",
        "          more lines that are more than 3 lines from any note)",
    ),
    r"""annotated-code = annotated-code(
  filename: "queue.py",
  language: "python",
  source: "def push(item):\n    queue.append(item)\n",
  notes: [
    {"lines": 2, "label": "Unbounded", "note": "`queue` has no limit.", "kind": "warn"},
  ],
)
""",
    validate_annotated_code,
)
