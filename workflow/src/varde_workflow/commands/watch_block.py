"""Render and atomically update the generated session-notes status block."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

BEGIN_MARKER = "<!-- varde:plan-status:begin -->"
END_MARKER = "<!-- varde:plan-status:end -->"
LOOKUP_LINE = (
    "lookup: varde plan status | varde plan show <id> | "
    "varde learn friction list --status open | git -C <worktree> log"
)
STUB = b"---\ntype: session-notes\nstatus: draft\n---\n"


@dataclass
class PlanState:
    label: str
    since: str | None = None

    def __str__(self) -> str:
        return f"stale since {self.since}" if self.label == "stale" else self.label


@dataclass
class PlanRow:
    id: str
    state: PlanState | str
    done: int
    total: int
    blocked: int = 0
    open_questions: int = 0
    now: str | None = None
    idle_no_handback: bool = False


@dataclass
class BlockModel:
    rows: list[PlanRow] = field(default_factory=list)
    blocked_tasks: list[str] = field(default_factory=list)


def render(model: BlockModel) -> str:
    lines = []
    for row in sorted(model.rows, key=lambda item: item.id):
        state = str(row.state)
        line = f"{row.id} [{state}] {row.done}/{row.total}"
        if row.blocked:
            line += f", {row.blocked} blocked"
        if row.open_questions:
            line += f" | q{row.open_questions}"
        if row.now and row.now.strip():
            line += " | " + row.now.strip().replace("<!--", "<!- -")
        if row.idle_no_handback:
            line += " | idle-no-handback"
        lines.append(line)
    if model.blocked_tasks:
        if lines:
            lines.append("")
        lines.append("blocked tasks: " + ", ".join(sorted(model.blocked_tasks)))
    if lines:
        lines.append("")
    lines.append(LOOKUP_LINE)
    return "\n".join(lines)


def _merge(original: bytes, body: str) -> bytes:
    begin, end = BEGIN_MARKER.encode(), END_MARKER.encode()
    starts = [i for i in range(len(original)) if original.startswith(begin, i)]
    ends = [i for i in range(len(original)) if original.startswith(end, i)]
    block = begin + b"\n" + body.encode() + b"\n" + end
    if not starts and not ends:
        base = original + (b"" if not original or original.endswith(b"\n") else b"\n")
        return base + begin + b"\n" + body.encode() + b"\n" + end + b"\n"
    if len(starts) != 1 or len(ends) != 1 or starts[0] > ends[0]:
        return original
    finish = ends[0] + len(end)
    updated = original[: starts[0]] + block + original[finish:]
    return updated if updated != original else original


def write_block(path: Path, model: BlockModel) -> None:
    path = path.resolve()
    original = path.read_bytes() if path.exists() else STUB
    updated = _merge(original, render(model))
    if updated == original:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
