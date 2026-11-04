"""Lossless codec for the human-edited queue markdown format."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueRow:
    values: dict[str, str]
    extra: dict[str, str]
    raw: str
    surplus: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueueDocument:
    title: str
    preamble: str
    header: tuple[str, ...]
    rows: tuple[QueueRow, ...]
    trailing: str
    separator: str
    newline: str = "\n"
    header_raw: str = ""


_KNOWN_COLUMNS = {
    "id",
    "plan dir",
    "findings",
    "owned files",
    "depends_on / serialize-with",
    "priority",
    "state",
    "planned_at",
    "plan_reviewed_at",
    "build_started_at",
    "build_done_at",
    "merged_at",
}


def _split_table_row(line: str) -> list[str]:
    """Split cells without treating pipes inside backtick spans as delimiters."""
    text = line.strip()
    text = text.removeprefix("|")
    text = text.removesuffix("|")
    cells: list[str] = []
    cell: list[str] = []
    ticks = False
    for char in text:
        if char == "`":
            ticks = not ticks
        if char == "|" and not ticks:
            cells.append("".join(cell).strip())
            cell = []
        else:
            cell.append(char)
    cells.append("".join(cell).strip())
    return cells


def parse_queue_md(text: str) -> QueueDocument:
    """Parse the first markdown table and retain all surrounding text."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    plain = [line.rstrip("\r\n") for line in lines]
    header_index = next(
        (
            i
            for i, line in enumerate(plain[:-1])
            if line.lstrip().startswith("|")
            and re.match(r"\s*\|?\s*:?-{3,}", plain[i + 1])
        ),
        -1,
    )
    if header_index < 0:
        if text.strip():
            raise ValueError("queue markdown contains no pipe table")
        return QueueDocument("", text, (), (), "", "")
    title = next((line for line in plain[:header_index] if line.startswith("# ")), "")
    preamble = "".join(lines[:header_index])
    header = tuple(_split_table_row(plain[header_index]))
    if len(set(header)) != len(header):
        raise ValueError("queue markdown table has duplicate column names")
    rows: list[QueueRow] = []
    index = header_index + 2
    while index < len(plain) and plain[index].lstrip().startswith("|"):
        cells = _split_table_row(plain[index])
        values = {
            key: cells[pos] if pos < len(cells) else ""
            for pos, key in enumerate(header)
        }
        extra = {
            key: value for key, value in values.items() if key not in _KNOWN_COLUMNS
        }
        rows.append(QueueRow(values, extra, lines[index], tuple(cells[len(header) :])))
        index += 1
    return QueueDocument(
        title,
        preamble,
        header,
        tuple(rows),
        "".join(lines[index:]),
        lines[header_index + 1],
        newline,
        lines[header_index],
    )


def render_queue_md(doc: QueueDocument) -> str:
    """Render rows from data while retaining untouched rows byte-for-byte."""
    if not doc.header:
        return doc.preamble
    rows = "".join(_render_row(doc.header, row, doc.newline) for row in doc.rows)
    return doc.preamble + doc.header_raw + doc.separator + rows + doc.trailing


def _render_row(header: tuple[str, ...], row: QueueRow, newline: str) -> str:
    original_cells = _split_table_row(row.raw.rstrip("\r\n"))
    current_cells = [row.values.get(column, "") for column in header]
    if (
        current_cells == original_cells[: len(header)]
        and list(row.surplus) == original_cells[len(header) :]
    ):
        return row.raw
    cells = current_cells + list(row.surplus)
    return "| " + " | ".join(cells) + " |" + newline


def parse_depends_cell(text: str) -> tuple[list[str], list[str]]:
    """Extract dependency and serialization ids from the queue cell."""
    if not text.strip() or text.strip().lower() == "none":
        return [], []
    deps: list[str] = []
    serial: list[str] = []
    for match in re.finditer(
        r"(?:plan\s+)?depends_on\s+([^;|]+)|serialize-with\s+([^;|]+)",
        text,
        re.IGNORECASE,
    ):
        target = serial if match.group(2) is not None else deps
        phrase = match.group(2) if match.group(2) is not None else match.group(1)
        leading = re.split(
            r"\s+on\s+|\s+first\b|\s+last\b|\s+\(",
            phrase or "",
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        leading = re.sub(
            r"\b(?:and|or|none|nothing|n/a)\b", " ", leading, flags=re.IGNORECASE
        )
        target.extend(re.findall(r"[A-Za-z0-9_.-]+", leading))
    return deps, serial
