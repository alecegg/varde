"""HTML for annotated-code: the code panel plus numbered notes anchored to line ranges.

Server-rendered. The panel comes from `render_code_panel`; this module adds a numbered
pin on the first line of each note, folds stretches of unannotated lines into a native
`<details>` row, and lists the notes. Pins and notes link to each other with plain
`href` anchors, so nothing needs JavaScript. Colours come only from `--vd-tone-*`.
"""

import hashlib
import json
import re
from dataclasses import dataclass

from varde_learn.docs.pages.blocks.annotated_code import (
    parse_range,
    source_line_count,
)
from varde_learn.docs.pages.blocks_render.callout import inline
from varde_learn.docs.pages.blocks_render.code import Panel, render_code_panel
from varde_learn.docs.pages.blocks_render.common import esc
from varde_learn.docs.pages.blocks_render.svg import copy_attr

CONTEXT = 3  # unannotated lines kept on each side of a note
MIN_FOLD = 4  # shortest quiet stretch worth a "lines hidden" row
KINDS = {
    "info": ("i", "Info", "info"),
    "warn": ("!", "Warning", "warning"),
    "change": ("Δ", "Change", "decision"),
}
_LINE_OPEN = re.compile(
    r'<span class="vd-code-line" data-line="(\d+)"( data-mark="1")?>'
)


@dataclass(frozen=True)
class Note:
    number: int
    start: int
    end: int
    label: str
    text: str
    kind: str

    @property
    def span_text(self) -> str:
        return (
            f"line {self.start}"
            if self.start == self.end
            else f"lines {self.start}-{self.end}"
        )


def read_notes(data: dict[str, object], total: int) -> list[Note]:
    """Notes numbered by start line (ties keep the author's order), ranges clamped."""
    found: list[tuple[int, int, int, dict[str, object]]] = []
    for index, raw in enumerate(data.get("notes") or []):  # type: ignore[attr-defined]
        span = parse_range(raw.get("lines"))
        if span is None:
            continue
        start = min(span[0], total)
        found.append((start, min(max(span[1], start), total), index, raw))
    found.sort(key=lambda item: (item[0], item[2]))
    return [
        Note(
            n,
            start,
            end,
            str(raw.get("label", "")),
            str(raw["note"]),
            str(raw.get("kind", "info")),
        )
        for n, (start, end, _, raw) in enumerate(found, 1)
    ]


def hidden_runs(notes: list[Note], total: int) -> list[tuple[int, int]]:
    """Runs of lines more than CONTEXT from any note, at least MIN_FOLD long."""
    kept: set[int] = set()
    for note in notes:
        kept.update(
            range(max(note.start - CONTEXT, 1), min(note.end + CONTEXT, total) + 1)
        )
    runs: list[tuple[int, int]] = []
    start = 0
    for line in range(1, total + 2):
        quiet = line <= total and line not in kept
        if quiet and not start:
            start = line
        if not quiet and start:
            runs.append((start, line - 1))
            start = 0
    return [(a, b) for a, b in runs if b - a + 1 >= MIN_FOLD]


def copy_text(source: str, notes: list[Note]) -> str:
    """The source, then the numbered notes."""
    listed = [
        f"{n.number}. {n.span_text}: " + (f"{n.label}: " if n.label else "") + n.text
        for n in notes
    ]
    return "\n\n".join(
        part for part in (source.rstrip("\n"), "\n".join(listed)) if part
    )


def _pin(block_id: str, note: Note) -> str:
    _, word, _ = KINDS[note.kind]
    name = f"Note {note.number}, {word.lower()}, {note.span_text}"
    return (
        f'<a class="vd-annotated-pin vd-annotated-k-{note.kind}" '
        f'id="pin-{block_id}-{note.number}" href="#note-{block_id}-{note.number}" '
        f'aria-label="{esc(name)}">{note.number}</a>'
    )


def _fold_row(first: int, last: int) -> str:
    count = last - first + 1
    return (
        '<summary class="vd-annotated-fold-row">'
        f'<span class="vd-annotated-fold-closed">'
        f"{count} lines hidden (lines {first}-{last})</span>"
        f'<span class="vd-annotated-fold-open">Hide lines {first}-{last}</span>'
        "</summary>"
    )


def decorate_lines(
    panel_html: str, block_id: str, notes: list[Note], folds: list[tuple[int, int]]
) -> str:
    """Add pins to the first line of each note and wrap hidden runs in `<details>`."""
    code_open = panel_html.index("<code")
    body_start = panel_html.index(">", code_open) + 1
    body_end = panel_html.rindex("</code>")
    chunks = _LINE_OPEN.split(panel_html[body_start:body_end])
    pins_at: dict[int, list[str]] = {}
    for note in notes:
        pins_at.setdefault(note.start, []).append(_pin(block_id, note))
    fold_at = {a: (a, b) for a, b in folds}
    out: list[str] = []
    closing = 0
    for i in range(1, len(chunks), 3):
        number, marked, rest = int(chunks[i]), chunks[i + 1], chunks[i + 2]
        if number in fold_at:
            out.append(
                f'<details class="vd-annotated-fold">{_fold_row(*fold_at[number])}'
            )
            closing = fold_at[number][1]
        pins = pins_at.get(number)
        klass = "vd-code-line vd-annotated-pinned" if pins else "vd-code-line"
        pin_html = (
            f'<span class="vd-annotated-pins">{"".join(pins)}</span>' if pins else ""
        )
        out.append(
            f'<span class="{klass}" data-line="{number}"{marked or ""}>{pin_html}{rest}'
        )
        if number == closing:
            out.append("</details>")
            closing = 0
    return panel_html[:body_start] + "".join(out) + panel_html[body_end:]


def _note_item(block_id: str, note: Note) -> str:
    glyph, word, tone = KINDS[note.kind]
    label = (
        f'<span class="vd-annotated-label">{esc(note.label)}</span>'
        if note.label
        else ""
    )
    return (
        f'<li class="vd-annotated-note vd-annotated-t-{tone}" '
        f'id="note-{block_id}-{note.number}" '
        f'tabindex="-1" data-from="{note.start}" data-to="{note.end}">'
        f'<a class="vd-annotated-back" href="#pin-{block_id}-{note.number}" '
        f'aria-label="Note {note.number}: back to {note.span_text}">{note.number}</a>'
        '<div class="vd-annotated-body"><p class="vd-annotated-meta">'
        f'<span class="vd-annotated-glyph" aria-hidden="true">{glyph}</span> {word}'
        f" · {note.span_text}</p>{label}"
        f'<p class="vd-annotated-text">{inline(note.text)}</p></div></li>'
    )


def render_annotated_code(data: dict[str, object]) -> str:
    source = str(data["source"])
    total = source_line_count(source)
    notes = read_notes(data, total)
    block_id = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:8]
    panel = Panel(
        title=str(data["filename"]), wrap=True, mark=[[n.start, n.end] for n in notes]
    )
    html = render_code_panel(source, str(data["language"]), panel)
    if not notes:
        return html.replace("vb code ", "vb annotated-code ", 1)
    folds = hidden_runs(notes, total) if data.get("collapse") is not False else []
    html = decorate_lines(html, block_id, notes, folds)
    html = html.replace("vb code ", "", 1)
    filename = esc(data["filename"])
    columns = min(max(sum(1 for m in notes if m.start == n.start) for n in notes), 6)
    items = "".join(_note_item(block_id, n) for n in notes)
    return (
        f'<div class="vb annotated-code vd-annotated-code vd-annotated-c{columns}"'
        f"{copy_attr(copy_text(source, notes))}>{html}"
        f'<ol class="vd-annotated-notes" aria-label="Notes on {filename}">{items}</ol>'
        "</div>"
    )
