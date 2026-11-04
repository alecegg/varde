"""One-line index over memory entries (pure logic)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from varde_learn.memory.entry import SCOPES, Entry

SUMMARY_LIMIT = 80


@dataclass(frozen=True)
class IndexLine:
    id: str
    scope: str
    summary: str
    tags: tuple[str, ...]


def summarize(text: str) -> str:
    stripped = text.strip()
    first = stripped.splitlines()[0] if stripped else ""
    return first[:SUMMARY_LIMIT]


def build_index(entries: Iterable[Entry]) -> list[IndexLine]:
    ordered = sorted(entries, key=lambda e: (SCOPES.index(e.scope), e.created, e.id))
    return [IndexLine(e.id, e.scope, summarize(e.text), e.tags) for e in ordered]


def render_index(lines: Iterable[IndexLine]) -> str:
    return "\n".join(
        f"{line.id} | {line.scope} | {line.summary} | {','.join(line.tags)}"
        for line in lines
    )
