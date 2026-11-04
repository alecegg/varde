"""Block type for source listings: code."""

from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    str_field,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec


def _is_line(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_range(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(_is_line(n) for n in value)
        and value[0] <= value[1]
    )


def _lines_faults(data: dict[str, object]) -> list[Fault]:
    if "lines" not in data or _is_range(data["lines"]):
        return []
    return [Fault("type", "code: 'lines' must be [from, to] with 1 <= from <= to")]


def _mark_faults(data: dict[str, object]) -> list[Fault]:
    if "mark" not in data:
        return []
    mark = data["mark"]
    if (
        isinstance(mark, list)
        and mark
        and all(_is_line(m) or _is_range(m) for m in mark)
    ):
        return []
    return [Fault("type", "code: 'mark' must be a list of line numbers or [from, to]")]


def _flag_faults(data: dict[str, object]) -> list[Fault]:
    return [
        Fault("type", f"code: '{key}' must be true or false")
        for key in ("wrap", "numbers")
        if key in data and not isinstance(data[key], bool)
    ]


def validate_code(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(
        data,
        {"language", "source"},
        {"title", "lines", "wrap", "numbers", "mark"},
        "code",
    )
    for key in ("language", "source", "title"):
        faults += str_field(data, key, "code")
    return faults + _lines_faults(data) + _mark_faults(data) + _flag_faults(data)


CODE = BlockSpec(
    "code",
    "A source listing with line numbers, optional marked lines and a Copy button",
    (
        "language  python, js, ts, json or shell are highlighted; others show plain",
        "source    the code, as one string",
        "title     optional file name or caption",
        "lines     optional [from, to]: show only those lines, numbered from `from`",
        "wrap      optional true: wrap long lines instead of scrolling sideways",
        "numbers   optional false: hide the line-number gutter",
        "mark      optional list of line numbers or [from, to] ranges to call out",
    ),
    r"""code = code(
  language: "python",
  title: "queue.py",
  source: "def push(item):\n    queue.append(item)\n",
  mark: [2],
)
""",
    validate_code,
)
