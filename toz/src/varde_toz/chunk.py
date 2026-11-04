"""Line-addressed chunks used by the toz SQLite store."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    title: str
    line_start: int
    line_end: int
    content_type: str
    body: str


def chunk_default(
    text: str, *, lines: int = 80, overlap: int = 10, _lines: list[str] | None = None
) -> list[Chunk]:
    if lines == 80 and overlap == 10:
        return chunk_content(text, _lines=_lines)
    return fixed_window(text, lines=lines, overlap=overlap, _lines=_lines)


def _fixed_window(
    text: str, *, lines: int = 80, overlap: int = 10, rows: list[str] | None = None
) -> list[Chunk]:
    rows = text.splitlines() if rows is None else rows
    if not rows:
        return []
    step = max(1, lines - overlap)
    chunks: list[Chunk] = []
    start = 0
    while start < len(rows):
        end = min(start + lines, len(rows))
        part = rows[start:end]
        title = next((line.strip() for line in part if line.strip()), "")
        if len(title) > 72:
            title = title[:71] + "…"
        nonblank = [line.rstrip() for line in part if line.strip()]
        codeish = sum(
            (line.startswith(("  ", "\t")) and any(c in line for c in "{};()=[]="))
            or line.endswith(("{", "}", ";", ",", ")"))
            for line in nonblank
        )
        chunks.append(
            Chunk(
                len(chunks),
                title,
                start + 1,
                end,
                "code" if nonblank and codeish * 10 > len(nonblank) * 4 else "prose",
                "\n".join(part),
            )
        )
        if end == len(rows):
            break
        start += step
    return chunks


def fixed_window(
    text: str, *, lines: int = 80, overlap: int = 10, _lines: list[str] | None = None
) -> list[Chunk]:
    return _fixed_window(text, lines=lines, overlap=overlap, rows=_lines)


def chunk_content(text: str, *, _lines: list[str] | None = None) -> list[Chunk]:
    from .strategies import chunk_default_content

    return chunk_default_content(text, lines=_lines)


def truncate(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    return value[: max(0, maximum - 1)] + "…"


def truncate_middle(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    tail = maximum // 3
    head = maximum - tail - 1
    return value[:head] + "…" + value[-tail:]


def title_for(lines: list[str]) -> str:
    return truncate(next((line.strip() for line in lines if line.strip()), ""), 72)


def strip_ansi(value: str) -> str:
    return re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|.)", "", value)


def classify(lines: list[str]) -> str:
    nonblank = [line.rstrip() for line in lines if line.strip()]
    codeish = sum(
        (line.startswith(("  ", "\t")) and any(char in line for char in "{};()=[]="))
        or line.endswith(("{", "}", ";", ",", ")"))
        for line in nonblank
    )
    return "code" if nonblank and codeish * 10 > len(nonblank) * 4 else "prose"


def looks_binary(data: bytes) -> bool:
    sample = data[:8192]
    if b"\0" in sample:
        return True
    non_text = sum(
        byte < 0x20 and byte not in (9, 10, 12, 13, 8, 27) for byte in sample
    )
    return bool(sample) and non_text * 100 // len(sample) > 5
