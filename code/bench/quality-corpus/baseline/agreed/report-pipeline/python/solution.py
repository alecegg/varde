import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import StringIO


@dataclass
class _Group:
    count: int = 0
    total: Decimal = Decimal("0")


def render_report(csv_text: str, key_column: str, value_column: str) -> str:
    """Sum `value_column` per `key_column` and render a text report.

    Returns "No data" for empty input or when there are no data rows.
    Raises ValueError for a missing column, a short row, or a value that
    is not a finite number. Duplicate headers bind to the first match.
    """
    reader = csv.reader(StringIO(csv_text), skipinitialspace=True)
    # Filter blanks on parsed rows, not physical lines, so quoted
    # embedded newlines survive.
    rows = (row for row in reader if any(field.strip() for field in row))

    header = next(rows, None)
    if header is None:
        return "No data"

    names = [name.strip() for name in header]
    try:
        key_index = names.index(key_column)
        value_index = names.index(value_column)
    except ValueError:
        raise ValueError(
            f"Missing column: need {key_column!r} and {value_column!r}"
        ) from None

    groups = _aggregate_by_key(rows, key_index, value_index)
    if not groups:
        return "No data"
    return _format_report(groups)


def _aggregate_by_key(rows, key_index: int, value_index: int) -> dict[str, _Group]:
    """Group rows by key; validates row length and that values are finite numbers."""
    groups: dict[str, _Group] = {}
    for row in rows:
        if max(key_index, value_index) >= len(row):
            raise ValueError(f"Row too short: {row!r}")
        raw_value = row[value_index].strip()
        try:
            value = Decimal(raw_value)
        except InvalidOperation:
            raise ValueError(f"Non-numeric value: {raw_value!r}") from None
        # Decimal accepts "NaN"/"Infinity", which would poison every total.
        if not value.is_finite():
            raise ValueError(f"Non-numeric value: {raw_value!r}")

        group = groups.setdefault(row[key_index].strip(), _Group())
        group.count += 1
        group.total += value
    return groups


def _format_report(groups: dict[str, _Group]) -> str:
    ordered = sorted(groups.items(), key=lambda item: (-item[1].total, item[0]))
    lines = [
        f"{key}: {group.count} rows, total {group.total:.2f}"
        for key, group in ordered
    ]
    row_count = sum(group.count for group in groups.values())
    grand_total = sum((group.total for group in groups.values()), Decimal("0"))
    lines.append(f"TOTAL: {row_count} rows, total {grand_total:.2f}")
    return "\n".join(lines)
