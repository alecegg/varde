"""HTML for diff: header, unified and side-by-side tables, folded runs, numbered notes.

Server-rendered, no JavaScript. Rows come from `blocks.diff_rows`. A `split` diff holds
both tables and the stylesheet shows one by container width, so the markup alone
reads fine. Status is never colour alone: each changed row has a `+` or `-` marker
and a hidden word. Colours come only from `--vd-tone-*` tokens.
"""

import hashlib
import json
from dataclasses import dataclass
from itertools import zip_longest

from varde_learn.docs.pages.blocks.annotated_code import parse_range
from varde_learn.docs.pages.blocks.diff_rows import (
    MAX_ROWS,
    Block,
    Row,
    change_word,
    diff_rows,
    layout,
    patch_rows,
    text_lines,
    unified_text,
)
from varde_learn.docs.pages.blocks_render.callout import inline
from varde_learn.docs.pages.blocks_render.change import change_badge, change_name
from varde_learn.docs.pages.blocks_render.code import line_html, split_lines, tokenize
from varde_learn.docs.pages.blocks_render.common import esc
from varde_learn.docs.pages.blocks_render.svg import copy_attr

MAX_DIGIT_CLASS = 6
MARKS = {"add": ("+", "added"), "del": ("-", "removed"), "same": ("", "")}


@dataclass(frozen=True)
class Note:
    number: int
    side: str
    start: int
    end: int
    text: str

    @property
    def where(self) -> str:
        lines = (
            f"line {self.start}"
            if self.start == self.end
            else f"lines {self.start}-{self.end}"
        )
        return f"{self.side} {lines}"


def read_notes(data: dict[str, object]) -> list[Note]:
    """Notes numbered in the author's order."""
    notes: list[Note] = []
    for raw in data.get("notes") or []:  # type: ignore[attr-defined]
        span = parse_range(raw.get("lines"))
        if span is None:
            continue
        notes.append(
            Note(len(notes) + 1, raw["side"], span[0], span[1], str(raw["note"]))
        )
    return notes


def anchored(notes: list[Note]) -> set[tuple[str, int]]:
    return {(n.side, line) for n in notes for line in range(n.start, n.end + 1)}


def row_html(rows: list[Row], language: str) -> list[str]:
    """Highlighted text of each row; each side is tokenized whole."""
    sides: dict[str, list[str]] = {}
    for side, has in (("old", lambda r: r.old), ("new", lambda r: r.new)):
        text = "\n".join(r.text for r in rows if has(r))
        lines = split_lines(tokenize(text, language)) if text else [[]]
        sides[side] = [line_html(line) for line in lines]
    out: list[str] = []
    counts = {"old": 0, "new": 0}
    for row in rows:
        use = "new" if row.new else "old"
        if row.old:
            counts["old"] += 1
        if row.new:
            counts["new"] += 1
        found = sides[use]
        index = counts[use] - 1
        out.append(found[index] if index < len(found) else esc(row.text))
    return out


def _pin(block_id: str, note: Note) -> str:
    return (
        f'<a class="vd-diff-pin" href="#note-{block_id}-{note.number}" '
        f'aria-label="Note {note.number}, {note.where}">{note.number}</a>'
    )


def _pins(block_id: str, notes: list[Note], side: str, line: int | None) -> str:
    if line is None:
        return ""
    found = [_pin(block_id, n) for n in notes if n.side == side and n.start == line]
    return f'<span class="vd-diff-pins">{"".join(found)}</span>' if found else ""


def _mark(kind: str) -> str:
    glyph, word = MARKS[kind]
    if not glyph:
        return '<td class="vd-diff-mark"></td>'
    return (
        f'<td class="vd-diff-mark"><span aria-hidden="true">{glyph}</span>'
        f'<span class="vd-diff-sr">{word}</span></td>'
    )


def _unified_row(row: Row, code: str, pins: str) -> str:
    old = "" if row.old is None else row.old
    new = "" if row.new is None else row.new
    return (
        f'<tr class="vd-diff-row vd-diff-{row.kind}">'
        f'<td class="vd-diff-num">{old}</td><td class="vd-diff-num">{new}</td>'
        f'{_mark(row.kind)}<td class="vd-diff-text">{pins}{code}</td></tr>'
    )


Item = tuple[Row, str]


@dataclass(frozen=True)
class View:
    """What drawing one table needs besides its rows."""

    block_id: str
    notes: list[Note]
    codes: dict[int, str]
    split: bool = False


def _pairs(items: list[Item]) -> list[tuple[Item | None, Item | None]]:
    """Side-by-side pairs: deletions go left and additions right."""
    pairs: list[tuple[Item | None, Item | None]] = []
    dels: list[Item] = []
    adds: list[Item] = []

    def flush() -> None:
        pairs.extend(zip_longest(dels, adds))
        dels.clear()
        adds.clear()

    for item in items:
        if item[0].kind == "del":
            dels.append(item)
        elif item[0].kind == "add":
            adds.append(item)
        else:
            flush()
            pairs.append((item, item))
    flush()
    return pairs


def _side_cells(item: Item | None, view: View, side: str) -> str:
    if item is None:
        return (
            '<td class="vd-diff-num vd-diff-empty"></td>'
            '<td class="vd-diff-mark vd-diff-empty"></td>'
            '<td class="vd-diff-text vd-diff-empty"></td>'
        )
    row, code = item
    number = row.old if side == "before" else row.new
    tone = f" vd-diff-{row.kind}"
    mark = _mark(row.kind).replace(
        'class="vd-diff-mark"', f'class="vd-diff-mark{tone}"'
    )
    pins = _pins(view.block_id, view.notes, side, number)
    return (
        f'<td class="vd-diff-num{tone}">{number}</td>{mark}'
        f'<td class="vd-diff-text{tone}">{pins}{code}</td>'
    )


def _split_row(left: Item | None, right: Item | None, view: View) -> str:
    return (
        '<tr class="vd-diff-row">'
        f"{_side_cells(left, view, 'before')}{_side_cells(right, view, 'after')}</tr>"
    )


def _cols(split: bool) -> str:
    side = '<col class="vd-diff-c-num"><col class="vd-diff-c-mark"><col>'
    if split:
        return f"<colgroup>{side}{side}</colgroup>"
    return (
        '<colgroup><col class="vd-diff-c-num"><col class="vd-diff-c-num">'
        '<col class="vd-diff-c-mark"><col></colgroup>'
    )


def _table(body: str, split: bool) -> str:
    return f'<table class="vd-diff-table">{_cols(split)}<tbody>{body}</tbody></table>'


def _hunk_row(header: str, split: bool) -> str:
    span = 6 if split else 4
    return f'<tr class="vd-diff-hunk"><td colspan="{span}">{esc(header)}</td></tr>'


def _body(rows: tuple[Row, ...], view: View) -> str:
    items = [(row, view.codes[id(row)]) for row in rows]
    if view.split:
        return "".join(_split_row(left, right, view) for left, right in _pairs(items))
    return "".join(
        _unified_row(
            row,
            code,
            _pins(view.block_id, view.notes, "before", row.old)
            + _pins(view.block_id, view.notes, "after", row.new),
        )
        for row, code in items
    )


def _fold(block: Block, view: View) -> str:
    count = len(block.rows)
    first, last = block.rows[0].new, block.rows[-1].new
    where = f" (lines {first}-{last})" if first and last else ""
    summary = (
        '<summary class="vd-diff-fold-row">'
        f'<span class="vd-diff-fold-closed">{count} unchanged lines hidden'
        f"{where}</span>"
        f'<span class="vd-diff-fold-open">Hide {count} unchanged lines</span></summary>'
    )
    table = _table(_body(block.rows, view), view.split)
    return f'<details class="vd-diff-fold">{summary}{table}</details>'


def _view(blocks: list[Block], view: View) -> str:
    out: list[str] = []
    for block in blocks:
        if block.kind == "rows":
            body = _hunk_row(block.header, view.split) + _body(block.rows, view)
            out.append(_table(body, view.split))
        elif block.kind == "fold":
            out.append(_fold(block, view))
        elif block.kind == "gap":
            text = f"{block.rows[0].text} unchanged lines not in the patch"
            out.append(f'<p class="vd-diff-gap">{text}</p>')
        else:
            out.append(
                f'<p class="vd-diff-more">{block.header} more lines not shown</p>'
            )
    return "".join(out)


def _region(kind: str, label: str, content: str) -> str:
    """A focusable scroll region around one view."""
    return (
        f'<div class="vd-diff-view {kind}" role="region" aria-label="{label}" '
        f'tabindex="0">{content}</div>'
    )


def _note_item(block_id: str, note: Note) -> str:
    return (
        f'<li class="vd-diff-note" id="note-{block_id}-{note.number}" tabindex="-1">'
        f'<span class="vd-diff-note-n">{note.number}</span>'
        '<div class="vd-diff-note-body">'
        f'<p class="vd-diff-note-meta">{esc(note.where)}</p>'
        f'<p class="vd-diff-note-text">{inline(note.text)}</p></div></li>'
    )


def _count_text(rows: list[Row]) -> str:
    added = sum(1 for r in rows if r.kind == "add")
    removed = sum(1 for r in rows if r.kind == "del")
    if not added and not removed:
        return "No changes"
    return f"+{added} added, -{removed} removed"


def _header(
    name: str, rows: list[Row], language: str, old_name: str, new_name: str
) -> str:
    change = change_word(rows, old_name, new_name)
    shown = change_name(esc(name), change, old_name) if change else esc(name)
    badge = change_badge(change) if change else ""
    lang = f'<span class="vd-diff-lang">{esc(language)}</span>' if language else ""
    return (
        '<figcaption class="vd-code-head vd-diff-head">'
        f'<span class="vd-diff-name">{shown}</span>{badge}'
        f'<span class="vd-diff-count">{esc(_count_text(rows))}</span>'
        f"{lang}</figcaption>"
    )


def render_diff(data: dict[str, object]) -> str:
    patch = data.get("patch")
    old_name = new_name = ""
    if isinstance(patch, str):
        rows, old_name, new_name = patch_rows(patch) or ([], "", "")
    else:
        rows = diff_rows(str(data["before"]), str(data["after"]))
    name = str(data.get("filename") or new_name or old_name or "diff")
    if isinstance(patch, str):
        copy = "\n".join(text_lines(patch))
    else:
        copy = unified_text(str(data["before"]), str(data["after"]), name)
    language = str(data.get("language", ""))
    notes = read_notes(data)
    block_id = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:8]
    shown = rows[:MAX_ROWS]
    codes = dict(zip(map(id, shown), row_html(shown, language), strict=True))
    blocks = layout(rows, anchored(notes))
    last = max([r.new or r.old or 0 for r in rows] + [1])
    digits = min(len(str(last)), MAX_DIGIT_CLASS)
    split = data.get("mode") == "split"
    unified = _view(blocks, View(block_id, notes, codes))
    label = esc(f"Diff of {name}")
    views = _region("vd-diff-unified", f"{label}, unified", unified)
    if split:
        side = _view(blocks, View(block_id, notes, codes, split=True))
        views += _region("vd-diff-sbs", f"{label}, side by side", side)
    items = "".join(_note_item(block_id, n) for n in notes)
    note_list = (
        f'<ol class="vd-diff-notes" aria-label="Notes on {esc(name)}">{items}</ol>'
        if notes
        else ""
    )
    classes = f"vb diff vd-code-panel vd-diff vd-diff-d{digits}" + (
        " vd-diff-split-mode" if split else ""
    )
    return (
        f'<figure class="{classes}"{copy_attr(copy)}>'
        f"{_header(name, rows, language, old_name, new_name)}"
        f"{views}{note_list}</figure>"
    )
