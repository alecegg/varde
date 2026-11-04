"""Lossless codec for the per-plan line queue format."""

from __future__ import annotations

import re
from dataclasses import dataclass

QUEUE_LINE_PATTERN = re.compile(
    r"^\s*(?P<task>[^|]+?)\s*\|\s*fix:(?P<fix>yes|no)\s*\|\s*"
    r"esc:(?P<escalations>\d+)\s*\|\s*worktree:(?P<worktree>[^|]+?)\s*$"
)
_QUEUE_LINE = QUEUE_LINE_PATTERN
_FORMAT_EXPECTATION = (
    "expected `<task-id> | fix:<yes|no> | esc:<n> | worktree:<path or ->`"
)


@dataclass(frozen=True)
class LineQueueRow:
    task: str
    markdown_values: tuple[tuple[str, str], ...]
    tail: str
    raw: str
    strict: bool


@dataclass(frozen=True)
class LineQueue:
    rows: tuple[LineQueueRow, ...]
    header: tuple[str, ...]
    passthrough: tuple[tuple[int, str], ...]
    layout: tuple[tuple[str, int | str], ...]


def parse_line_queue(text: str) -> LineQueue:
    """Parse line items while retaining non-item lines and their positions."""
    rows: list[LineQueueRow] = []
    header: list[str] = []
    passthrough: list[tuple[int, str]] = []
    layout: list[tuple[str, int | str]] = []
    saw_row = False
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith("#") or " | " not in line:
            if saw_row:
                passthrough.append((len(rows), raw))
            else:
                header.append(raw)
            layout.append(("raw", raw))
            continue
        fields = line.split(" | ")
        task = fields[0].strip()
        values: list[tuple[str, str]] = []
        tail = ""
        for field in fields[1:]:
            if ":" not in field:
                tail = field
                break
            key, value = field.split(":", 1)
            # Two or more spaces mark free-text tail after the final key:value.
            tail_match = re.fullmatch(r"(.*?)[ \t]{2,}(\S.*)", value)
            if tail_match is None:
                values.append((key.strip(), value.strip()))
                continue
            values.append((key.strip(), tail_match.group(1).strip()))
            tail = tail_match.group(2)
            break
        row = LineQueueRow(
            task, tuple(values), tail, raw, _QUEUE_LINE.fullmatch(line) is not None
        )
        rows.append(row)
        layout.append(("row", len(rows) - 1))
        saw_row = True
    return LineQueue(tuple(rows), tuple(header), tuple(passthrough), tuple(layout))


def render_line_queue(queue: LineQueue) -> str:
    """Render original lines unchanged and canonicalize rows without raw text."""
    output: list[str] = []
    for kind, value in queue.layout:
        if kind == "raw":
            output.append(str(value))
            continue
        row = queue.rows[int(value)]
        if row.raw:
            output.append(row.raw)
            continue
        fields = [f"{key}:{field}" for key, field in row.markdown_values]
        if row.tail:
            if fields:
                fields[-1] += f"  {row.tail}"
            else:
                fields.append(row.tail)
        output.append(" | ".join([row.task, *fields]) + "\n")
    return "".join(output)


def validate_line_queue(text: str, path: str) -> None:
    """Raise the production queue format error for the first invalid item line."""
    seen: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _QUEUE_LINE.fullmatch(line)
        if match is None:
            raise line_queue_format_error(path, line_number)
        task_id = match.group("task").strip()
        if task_id in seen:
            raise ValueError(f"{path}:{line_number}: duplicate task: {task_id}")
        seen.add(task_id)


def line_queue_format_error(path: str, line_number: int) -> ValueError:
    """Build the canonical malformed-line error shared with queue_check."""
    return ValueError(f"{path}:{line_number}: {_FORMAT_EXPECTATION}")
