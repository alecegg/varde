"""Block type for a decision matrix: matrix (options as columns, criteria as rows)."""

from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    duplicates,
    str_field,
    tables,
    tables_fault,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec

SCALES = {
    "verdict": {"yes": 2, "partial": 1, "no": 0},
    "level": {"high": 2, "medium": 1, "low": 0},
}
MAX_OPTIONS = 12
MAX_CRITERIA = 200
FIRST_COLUMN = "Criterion"


def rating_scale(cell: object) -> str | None:
    """The scale a cell's rating belongs to, or None when the cell is plain text."""
    word = cell.strip().lower() if isinstance(cell, str) else ""
    return next((name for name, words in SCALES.items() if word in words), None)


def _entry_faults(data: dict[str, object], key: str, extra: set[str]) -> list[Fault]:
    faults = tables_fault(data, key, "matrix")
    for n, entry in enumerate(tables(data, key, "matrix"), 1):
        where = f"matrix.{key}[{n}]"
        faults += check_keys(entry, {"id", "label"}, extra, where)
        for field in ("id", "label", *sorted(extra - {"weight"})):
            faults += str_field(entry, field, where)
    return faults


def _unique_faults(data: dict[str, object], key: str, field: str) -> list[Fault]:
    names = [str(e.get(field)) for e in tables(data, key, "matrix") if field in e]
    return [
        Fault("duplicate", f"matrix.{key}: {field} '{name}' is repeated")
        for name in duplicates(names)
    ]


def _option_faults(data: dict[str, object]) -> list[Fault]:
    faults = _entry_faults(data, "options", {"note"})
    options = tables(data, "options", "matrix")
    if len(options) > MAX_OPTIONS:
        faults.append(Fault("limit", f"matrix: at most {MAX_OPTIONS} options"))
    if any(o.get("label") == FIRST_COLUMN for o in options):
        faults.append(
            Fault("duplicate", f"matrix.options: label '{FIRST_COLUMN}' is reserved")
        )
    return (
        faults
        + _unique_faults(data, "options", "id")
        + _unique_faults(data, "options", "label")
    )


def _weight_faults(data: dict[str, object]) -> list[Fault]:
    faults: list[Fault] = []
    for n, entry in enumerate(tables(data, "criteria", "matrix"), 1):
        weight = entry.get("weight")
        if "weight" in entry and (
            not isinstance(weight, int)
            or isinstance(weight, bool)
            or not 1 <= weight <= 5
        ):
            faults.append(
                Fault(
                    "type",
                    f"matrix.criteria[{n}].weight must be a whole number from 1 to 5",
                )
            )
    return faults


def _criteria_faults(data: dict[str, object]) -> list[Fault]:
    faults = _entry_faults(data, "criteria", {"weight"})
    faults += _weight_faults(data)
    if len(tables(data, "criteria", "matrix")) > MAX_CRITERIA:
        faults.append(Fault("limit", f"matrix: at most {MAX_CRITERIA} criteria"))
    return faults + _unique_faults(data, "criteria", "id")


def _grid_faults(data: dict[str, object]) -> list[Fault]:
    cells = data["cells"]
    options = tables(data, "options", "matrix")
    criteria = tables(data, "criteria", "matrix")
    if not isinstance(cells, list) or not all(isinstance(r, list) for r in cells):
        return [
            Fault("type", "matrix: 'cells' must be a list of rows, one per criterion")
        ]
    faults: list[Fault] = []
    if len(cells) != len(criteria):
        faults.append(
            Fault(
                "cells-rows",
                f"matrix.cells has {len(cells)} rows, "
                f"expected {len(criteria)} (one per criterion)",
            )
        )
    for n, row in enumerate(cells, 1):
        name = criteria[n - 1].get("label") if n <= len(criteria) else None
        where = f"matrix.cells[{n}]" + (f" ('{name}')" if isinstance(name, str) else "")
        if len(row) != len(options):
            faults.append(
                Fault(
                    "cells-width",
                    f"{where} has {len(row)} cells, "
                    f"expected {len(options)} (one per option)",
                )
            )
        if not all(isinstance(c, str) for c in row):
            faults.append(Fault("type", f"{where}: each cell must be a string"))
    scales = {rating_scale(c) for row in cells for c in row} - {None}
    if len(scales) > 1:
        faults.append(
            Fault(
                "scale",
                "matrix.cells mix the yes/partial/no and high/medium/low scales",
            )
        )
    return faults


def _recommended_faults(data: dict[str, object]) -> list[Fault]:
    if "recommended" not in data:
        return []
    faults = str_field(data, "recommended", "matrix")
    ids = [o.get("id") for o in tables(data, "options", "matrix")]
    if not faults and data["recommended"] not in ids:
        faults.append(
            Fault(
                "recommended",
                f"matrix.recommended: no option with id '{data['recommended']}'",
            )
        )
    return faults


def validate_matrix(data: dict[str, object]) -> list[Fault]:
    required = {"options", "criteria", "cells"}
    faults = check_keys(data, required, {"title", "recommended"}, "matrix")
    faults += str_field(data, "title", "matrix")
    if "options" in data:
        faults += _option_faults(data)
    if "criteria" in data:
        faults += _criteria_faults(data)
    if required <= data.keys() and not faults:
        faults += _grid_faults(data)
    return faults + _recommended_faults(data)


MATRIX = BlockSpec(
    "matrix",
    "A decision matrix: options as columns, criteria as rows, ratings in cells",
    (
        "title        optional heading",
        "options      list of {id, label, note}, 1 to 12; label is the column name",
        "criteria     list of {id, label, weight}, up to 200; weight is 1 to 5",
        "cells        list of rows, one per criterion; a row has one cell per option",
        "             a cell is yes, partial or no, or high, medium or low (one",
        "             scale per matrix), or plain text; empty reads 'Not rated'",
        "recommended  optional option id: its column gets a Recommended badge",
        "  Any weight adds a 'Weighted total' row (unweighted criteria count 1; yes",
        "  or high scores 2, partial or medium 1, no or low 0; text scores 0).",
        "  Rows stack on phones; sort and filter come from the table block.",
    ),
    r"""matrix = matrix(
  title: "Queue options",
  options: [
    {"id": "db", "label": "SQLite", "note": "One writer is enough."},
    {"id": "mq", "label": "Broker"},
  ],
  criteria: [
    {"id": "ops", "label": "Easy to run", "weight": 3},
    {"id": "scale", "label": "Scales out", "weight": 1},
  ],
  cells: [["yes", "no"], ["no", "yes"]],
  recommended: "db",
)
""",
    validate_matrix,
)
