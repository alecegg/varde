"""Block type for a before and after text diff: diff."""

from varde_learn.docs.pages.blocks.annotated_code import parse_range
from varde_learn.docs.pages.blocks.diff_rows import MAX_ROWS, patch_rows, text_lines
from varde_learn.docs.pages.blocks.rules import Fault, check_keys, str_field
from varde_learn.docs.pages.blocks.spec import BlockSpec

MODES = ("unified", "split")
SIDES = ("before", "after")
MAX_NOTES = 40


def _text_faults(data: dict[str, object]) -> list[Fault]:
    faults = [
        Fault("type", f"diff: '{key}' must be a string")
        for key in ("before", "after", "patch")
        if key in data and not isinstance(data[key], str)
    ]
    if "patch" in data and ("before" in data or "after" in data):
        faults.append(Fault("input", "diff: give patch or before and after"))
    if "patch" not in data and not ("before" in data and "after" in data):
        faults.append(Fault("input", "diff: give before and after, or patch"))
    return faults


def _limit_faults(data: dict[str, object]) -> list[Fault]:
    faults: list[Fault] = []
    for key in ("before", "after", "patch"):
        value = data.get(key)
        if isinstance(value, str) and len(text_lines(value)) > MAX_ROWS:
            faults.append(
                Fault(
                    "limit",
                    f"diff: '{key}' has more than {MAX_ROWS} lines; the rest is cut",
                )
            )
    patch = data.get("patch")
    if isinstance(patch, str) and patch.strip() and patch_rows(patch) is None:
        faults.append(Fault("type", "diff: 'patch' has no '@@ -a,b +c,d @@' hunk"))
    return faults


def _side_total(data: dict[str, object], side: str) -> int | None:
    value = data.get(side)
    return len(text_lines(value)) if isinstance(value, str) else None


def _note_faults(note: object, where: str, data: dict[str, object]) -> list[Fault]:
    if not isinstance(note, dict):
        return [Fault("type", f"{where} must be a table")]
    faults = check_keys(note, {"side", "lines", "note"}, set(), where)
    faults += str_field(note, "note", where)
    side = note.get("side")
    if "side" in note and side not in SIDES:
        faults.append(Fault("type", f"{where}: side must be before or after"))
    if "lines" not in note:
        return faults
    span = parse_range(note["lines"])
    if span is None:
        return faults + [Fault("type", f"{where}: lines must be n or 'from-to'")]
    total = _side_total(data, side) if isinstance(side, str) else None
    if total is not None and span[1] > total:
        faults.append(
            Fault("range", f"{where}: lines {span[0]}-{span[1]} pass line {total}")
        )
    return faults


def _notes_faults(data: dict[str, object]) -> list[Fault]:
    notes = data["notes"]
    if not isinstance(notes, list):
        return [Fault("type", "diff: 'notes' must be a list of tables")]
    faults: list[Fault] = []
    if len(notes) > MAX_NOTES:
        faults.append(Fault("limit", f"diff: at most {MAX_NOTES} notes"))
    for i, note in enumerate(notes, 1):
        faults += _note_faults(note, f"diff: notes[{i}]", data)
    return faults


def validate_diff(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(
        data,
        set(),
        {"filename", "before", "after", "patch", "mode", "language", "notes"},
        "diff",
    )
    for key in ("filename", "language"):
        faults += str_field(data, key, "diff")
    if "mode" in data and data["mode"] not in MODES:
        faults.append(Fault("type", "diff: mode must be unified or split"))
    faults += _text_faults(data) + _limit_faults(data)
    return faults + (_notes_faults(data) if "notes" in data else [])


DIFF = BlockSpec(
    "diff",
    "A before and after text diff, unified or split, with notes on changed lines",
    (
        "filename  optional file name shown in the header",
        "before    the old text, as one string (may be empty: an added file)",
        "after     the new text, as one string (may be empty: a removed file)",
        "patch     instead of before and after: a unified diff string",
        "mode      optional: unified (default) or split (two columns when wide)",
        "language  optional: python, js, ts, json or shell are highlighted",
        "notes     optional list of {side, lines, note}, up to 40; side is before",
        "          or after; lines is n or 'from-to' on that side",
        "  Unchanged runs over 6 lines fold to 3 at each edge; noted lines stay.",
        "  At most 5000 lines are drawn; the rest shows as one 'N more lines' row.",
    ),
    r"""diff = diff(
  filename: "queue.py",
  language: "python",
  before: "def push(item):\n    queue.append(item)\n",
  after: "def push(item):\n    if not item:\n        return\n    queue.append(item)\n",
  mode: "unified",
  notes: [{"side": "after", "lines": "2-3", "note": "Skip empty items."}],
)
""",
    validate_diff,
)
