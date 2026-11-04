"""Multi-file unified diffs for proposals: build and strictly apply (pure).

Headers carry absolute paths: `--- <path>` / `+++ <path>`; a file that does not
exist yet uses `--- /dev/null`; a file to delete ends `+++ /dev/null`.
`ABSENT` is the pre-image hash of a file that does not exist yet.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

ABSENT = ""
NULL = "/dev/null"
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class DiffError(ValueError):
    """A diff is malformed or does not match the file it is applied to."""


@dataclass(frozen=True)
class FileDiff:
    path: str
    creates: bool
    lines: tuple[str, ...]  # hunk lines, `@@` headers included
    deletes: bool = False


def split_lines(text: str) -> list[str]:
    """Lines with their `\\n` kept; only `\\n` ends a line (CR, FF, U+2028 stay)."""
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    return lines + [parts[-1]] if parts[-1] else lines


def make_file_diff(path: str, old: str | None, new: str | None) -> str:
    """Unified diff turning `old` (None: no file) into `new` (None: delete)."""
    old_lines = split_lines(old or "")
    out = difflib.unified_diff(
        old_lines,
        split_lines(new or ""),
        NULL if old is None else path,
        NULL if new is None else path,
        n=3,
        lineterm="\n",
    )
    text = "".join(_terminate(line) for line in out)
    if text or (old is None) == (new is None):
        return text
    return f"--- {NULL if old is None else path}\n+++ {NULL if new is None else path}\n"


def _terminate(line: str) -> str:
    return line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"


def parse_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    index = 0
    while index < len(lines):
        if not _is_header(lines, index):
            raise DiffError(f"unexpected line: {lines[index]!r}")
        source = lines[index][4:]
        target = lines[index + 1][4:]
        if source == NULL and target == NULL:
            raise DiffError("diff header has /dev/null on both sides")
        path = source if target == NULL else target
        index += 2
        start = index
        while index < len(lines) and not _is_header(lines, index):
            index += 1
        files.append(
            FileDiff(path, source == NULL, tuple(lines[start:index]), target == NULL)
        )
    return files


def _is_header(lines: list[str], index: int) -> bool:
    following = lines[index + 1] if index + 1 < len(lines) else ""
    return lines[index].startswith("--- ") and following.startswith("+++ ")


def apply_file_diff(old: str, diff: FileDiff) -> str:
    """Apply hunks to `old`; any context or removal mismatch raises."""
    source = split_lines(old)
    result: list[str] = []
    cursor = 0
    index = 0
    lines = diff.lines
    while index < len(lines):
        match = _HUNK.match(lines[index])
        if match is None:
            raise DiffError(f"expected hunk header: {lines[index]!r}")
        start = int(match[1]) - (1 if match[2] != "0" else 0)
        result.extend(source[cursor:start])
        cursor = start
        index += 1
        while index < len(lines) and not lines[index].startswith("@@"):
            line = lines[index]
            if line.startswith("\\"):
                if lines[index - 1][:1] != "-":
                    result[-1] = result[-1].removesuffix("\n")
            else:
                cursor = _apply_line(line, source, cursor, result)
            index += 1
    result.extend(source[cursor:])
    return "".join(result)


def _apply_line(line: str, source: list[str], cursor: int, result: list[str]) -> int:
    mark, body = line[:1], line[1:] + "\n"
    if mark == "+":
        result.append(body)
        return cursor
    current = source[cursor] if cursor < len(source) else None
    if current is None or current.rstrip("\n") != body.rstrip("\n"):
        raise DiffError(f"hunk does not match near: {body.rstrip()!r}")
    if mark == " ":
        result.append(current)
    return cursor + 1
