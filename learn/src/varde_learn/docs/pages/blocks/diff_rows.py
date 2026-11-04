"""Pure model for the diff block: line rows, folding, hunk headers, unified text.

No HTML and no I/O. `diff_rows` is a stdlib `difflib` line diff, deterministic, with
no timestamps. A patch string becomes the same rows, so both inputs render alike.
"""

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass

MAX_ROWS = 5000  # rows drawn; the rest becomes one "N more lines" row
CONTEXT = 3  # unchanged lines kept next to a change when a run folds
FOLD_OVER = 6  # an unchanged run longer than this folds to CONTEXT at each edge
MIN_HIDDEN = 2  # hiding a single line saves nothing
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class Row:
    kind: str  # same, del, add or gap (gap: `text` is the count of lines not shown)
    old: int | None
    new: int | None
    text: str


@dataclass(frozen=True)
class Block:
    kind: str  # rows, fold, gap or more
    rows: tuple[Row, ...]
    header: str = ""  # rows: the hunk header; more: the count


def text_lines(text: str) -> list[str]:
    """Lines of a text; CRLF and CR are newlines and a closing newline adds none."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and not lines[-1]:
        lines.pop()
    return lines


def diff_rows(before: str, after: str) -> list[Row]:
    """Line diff of two texts: deletions before additions inside a changed block."""
    old, new = text_lines(before), text_lines(after)
    rows: list[Row] = []
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            rows += [
                Row("same", i + 1, j + 1, old[i])
                for i, j in zip(range(i1, i2), range(j1, j2), strict=True)
            ]
            continue
        rows += [Row("del", i + 1, None, old[i]) for i in range(i1, i2)]
        rows += [Row("add", None, j + 1, new[j]) for j in range(j1, j2)]
    return rows


def _patch_name(line: str) -> str:
    name = line[4:].split("\t")[0].strip()
    if name == "/dev/null":
        return ""
    return name[2:] if name[:2] in ("a/", "b/") else name


def _hunk_rows(
    lines: list[str], at: int, counts: tuple[int, int], start: tuple[int, int]
) -> tuple[list[Row], int]:
    """Rows of the hunk body that begins at `lines[at]`; also the index after it."""
    old_left, new_left = counts
    old, new = start
    rows: list[Row] = []
    while at < len(lines) and (old_left > 0 or new_left > 0):
        line = lines[at]
        at += 1
        mark, text = line[:1], line[1:]
        if mark == "\\":
            continue
        if mark == "-":
            rows.append(Row("del", old, None, text))
            old, old_left = old + 1, old_left - 1
        elif mark == "+":
            rows.append(Row("add", None, new, text))
            new, new_left = new + 1, new_left - 1
        else:
            rows.append(Row("same", old, new, text))
            old, new = old + 1, new + 1
            old_left, new_left = old_left - 1, new_left - 1
    return rows, at


def patch_rows(patch: str) -> tuple[list[Row], str, str] | None:
    """Rows, old name and new name of a unified diff; None when it has no hunk."""
    lines = text_lines(patch)
    old_name = new_name = ""
    rows: list[Row] = []
    next_old = 1
    at = 0
    while at < len(lines):
        line = lines[at]
        match = _HUNK.match(line)
        if not match:
            if not rows and line.startswith("--- "):
                old_name = _patch_name(line)
            if not rows and line.startswith("+++ "):
                new_name = _patch_name(line)
            at += 1
            continue
        old_count = int(match[2]) if match[2] is not None else 1
        new_count = int(match[4]) if match[4] is not None else 1
        first_old = int(match[1]) + (0 if old_count else 1)
        first_new = int(match[3]) + (0 if new_count else 1)
        if first_old > next_old:
            rows.append(Row("gap", None, None, str(first_old - next_old)))
        found, at = _hunk_rows(
            lines, at + 1, (old_count, new_count), (first_old, first_new)
        )
        rows += found
        next_old = max([r.old + 1 for r in found if r.old] + [first_old])
    return (rows, old_name, new_name) if rows else None


def _hidden_runs(keep: list[bool]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start = None
    for i, kept in enumerate([*keep, True]):
        if not kept and start is None:
            start = i
        if kept and start is not None:
            runs.append((start, i))
            start = None
    return runs


def keep_mask(rows: list[Row], anchors: set[tuple[str, int]]) -> list[bool]:
    """Rows that stay visible: changes, run edges and anchored rows (no lone gaps)."""
    keep = [row.kind != "same" for row in rows]
    i = 0
    while i < len(rows):
        if keep[i]:
            i += 1
            continue
        j = i
        while j < len(rows) and not keep[j]:
            j += 1
        if j - i <= FOLD_OVER:
            keep[i:j] = [True] * (j - i)
        else:
            keep[i : i + CONTEXT] = [True] * CONTEXT if i > 0 else [False] * CONTEXT
            keep[j - CONTEXT : j] = (
                [True] * CONTEXT if j < len(rows) else [False] * CONTEXT
            )
        i = j
    for k, row in enumerate(rows):
        if ("before", row.old or 0) in anchors or ("after", row.new or 0) in anchors:
            keep[k] = True
    for a, b in _hidden_runs(keep):
        if b - a < MIN_HIDDEN:
            keep[a:b] = [True] * (b - a)
    return keep


def hunk_header(rows: tuple[Row, ...], last_old: int, last_new: int) -> str:
    """`@@ -a,b +c,d @@` for rows; an empty side starts at the line before it."""
    olds = [r.old for r in rows if r.old]
    news = [r.new for r in rows if r.new]

    def span(numbers: Sequence[int | None], last: int) -> str:
        count = len(numbers)
        first = numbers[0] if numbers else last
        return f"{first}" if count == 1 else f"{first},{count}"

    return f"@@ -{span(olds, last_old)} +{span(news, last_new)} @@"


def layout(rows: list[Row], anchors: set[tuple[str, int]]) -> list[Block]:
    """Rows cut into visible runs with hunk headers, folds, patch gaps and a cap row."""
    total = len(rows)
    rows = rows[:MAX_ROWS]
    keep = keep_mask(rows, anchors)
    blocks: list[Block] = []
    last_old = last_new = 0
    start = 0
    for i in range(1, len(rows) + 1):
        edge = i == len(rows) or rows[i].kind == "gap" or rows[i - 1].kind == "gap"
        if not edge and keep[i] == keep[i - 1]:
            continue
        chunk = tuple(rows[start:i])
        if chunk[0].kind == "gap":
            blocks.append(Block("gap", chunk))
        elif keep[start]:
            blocks.append(Block("rows", chunk, hunk_header(chunk, last_old, last_new)))
        else:
            blocks.append(Block("fold", chunk))
        last_old = max([r.old for r in chunk if r.old] + [last_old])
        last_new = max([r.new for r in chunk if r.new] + [last_new])
        start = i
    if total > MAX_ROWS:
        blocks.append(Block("more", (), str(total - MAX_ROWS)))
    return blocks


def unified_text(before: str, after: str, name: str) -> str:
    """The unified diff of two texts, three lines of context, no timestamps."""
    body = list(
        difflib.unified_diff(
            text_lines(before), text_lines(after), fromfile="", tofile="", lineterm=""
        )
    )[2:]
    return "\n".join([f"--- a/{name}", f"+++ b/{name}", *body])


def change_word(rows: list[Row], old_name: str, new_name: str) -> str:
    """added, removed, renamed or modified; empty when nothing changed."""
    if old_name and new_name and old_name != new_name:
        return "renamed"
    if not any(row.kind != "same" for row in rows if row.kind != "gap"):
        return ""
    has_old = any(row.old for row in rows)
    has_new = any(row.new for row in rows)
    if has_new and not has_old:
        return "added"
    if has_old and not has_new:
        return "removed"
    return "modified"
