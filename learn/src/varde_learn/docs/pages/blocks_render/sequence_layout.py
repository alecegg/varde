"""Deterministic geometry for the sequence block. Pure integer arithmetic, no SVG.

Actors sit in equal-spaced columns sized from their label width; each step takes one
row whose height follows its wrapped text; groups are frames over runs of rows.
`layout(actors, steps)` returns the same `Geometry` for the same input.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from varde_learn.docs.pages.blocks_render.svg import wrap_text

Props = Mapping[str, object]

CHAR_W = 8  # generous width of one 13px character
LINE_H = 16
PAD = 24
HEAD_H = 44
ROW_MIN = 44
MIN_GAP = 150
MIN_BOX = 72
MAX_BOX = 160
LABEL_CHARS = 16
LABEL_LINES = 2
TEXT_LINES = 3
LOOP_W = 36
GROUP_HEAD = 26
GROUP_FOOT = 8
NOTE_PAD = 10


@dataclass(frozen=True)
class Actor:
    index: int
    id: str
    label: str
    lines: tuple[str, ...]
    x: int  # lifeline
    box_x: int
    box_w: int

    @property
    def truncated(self) -> bool:
        return " ".join(self.lines) != " ".join(self.label.split())


@dataclass(frozen=True)
class Row:
    index: int
    kind: str
    lines: tuple[str, ...]
    x1: int  # arrow start (note: box left)
    x2: int  # arrow end (note: box right)
    y: int
    h: int
    arrow_y: int
    self_call: bool
    text_x: int
    anchor: str  # SVG text-anchor


@dataclass(frozen=True)
class Frame:
    label: str
    y: int
    h: int


@dataclass(frozen=True)
class Geometry:
    width: int
    height: int
    actors: tuple[Actor, ...]
    rows: tuple[Row, ...]
    frames: tuple[Frame, ...]


def clip_lines(text: str, chars: int, limit: int) -> tuple[str, ...]:
    """Wrap to `chars`, keep `limit` lines, mark a cut with an ellipsis."""
    lines = wrap_text(text, chars) or [""]
    if len(lines) <= limit:
        return tuple(lines)
    kept = lines[:limit]
    kept[-1] = kept[-1][: max(chars - 1, 1)] + "…"
    return tuple(kept)


def _box_width(lines: Sequence[str]) -> int:
    widest = max((len(line) for line in lines), default=1)
    return min(max(widest * CHAR_W + 20, MIN_BOX), MAX_BOX)


def place_actors(actors: Sequence[Props]) -> tuple[Actor, ...]:
    wrapped = [clip_lines(str(a["label"]), LABEL_CHARS, LABEL_LINES) for a in actors]
    widest = max((_box_width(lines) for lines in wrapped), default=MIN_BOX)
    gap = max(MIN_GAP, widest + 20)
    return tuple(
        Actor(
            i,
            str(a["id"]),
            str(a["label"]),
            lines,
            x := PAD + gap // 2 + i * gap,
            x - _box_width(lines) // 2,
            _box_width(lines),
        )
        for i, (a, lines) in enumerate(zip(actors, wrapped, strict=True))
    )


def _gap(actors: tuple[Actor, ...]) -> int:
    return actors[1].x - actors[0].x if len(actors) > 1 else MIN_GAP


def _arrow_row(index: int, kind: str, text: str, a: int, b: int, y: int) -> Row:
    chars = max((abs(b - a) - 24) // CHAR_W, 6)
    lines = clip_lines(text, chars, TEXT_LINES)
    arrow_y = y + LINE_H * len(lines) + 14
    return Row(
        index, kind, lines, a, b, y, max(ROW_MIN, arrow_y - y + 14), arrow_y,
        False, (a + b) // 2, "middle",
    )  # fmt: skip


def _self_row(index: int, kind: str, text: str, x: int, gap: int, y: int) -> Row:
    lines = clip_lines(text, max((gap - 56) // CHAR_W, 6), TEXT_LINES)
    h = max(ROW_MIN, LINE_H * len(lines) + 16)
    return Row(
        index, kind, lines, x, x, y, h, y + 12, True, x + LOOP_W + 8, "start"
    )  # fmt: skip


def _note_row(index: int, text: str, a: int, b: int, gap: int, y: int) -> Row:
    left, right = min(a, b), max(a, b)
    if left == right:
        left, right = left - (gap - 20) // 2, right + (gap - 20) // 2
    else:
        left, right = left - NOTE_PAD, right + NOTE_PAD
    lines = clip_lines(text, max((right - left - 16) // CHAR_W, 6), TEXT_LINES)
    h = max(ROW_MIN, LINE_H * len(lines) + 24)
    return Row(
        index, "note", lines, left, right, y, h, y + h // 2, False,
        (left + right) // 2, "middle",
    )  # fmt: skip


def _row(index: int, step: Props, by_id: Mapping[str, Actor], gap: int, y: int) -> Row:
    a, b = by_id[str(step["from"])], by_id[str(step["to"])]
    kind, text = str(step.get("kind", "call")), str(step["text"])
    if kind == "note":
        return _note_row(index, text, a.x, b.x, gap, y)
    if a.x == b.x:
        return _self_row(index, kind, text, a.x, gap, y)
    return _arrow_row(index, kind, text, a.x, b.x, y)


def _right_edge(row: Row) -> int:
    if row.anchor != "start":
        return row.x2
    return row.text_x + max((len(line) for line in row.lines), default=0) * CHAR_W


def layout(actors: Sequence[Props], steps: Sequence[Props]) -> Geometry:
    placed = place_actors(actors)
    by_id = {a.id: a for a in placed}
    gap = _gap(placed)
    rows: list[Row] = []
    frames: list[Frame] = []
    y = HEAD_H + 12
    open_label: str | None = None
    open_at = 0
    for i, step in enumerate(steps):
        group = str(step["group"]) if "group" in step else None
        if group != open_label:
            if open_label is not None:
                frames.append(Frame(open_label, open_at, y - open_at + GROUP_FOOT))
                y += GROUP_FOOT + 4
            open_label, open_at = group, y
            y += GROUP_HEAD if group is not None else 0
        row = _row(i, step, by_id, gap, y)
        rows.append(row)
        y += row.h
    if open_label is not None:
        frames.append(Frame(open_label, open_at, y - open_at + GROUP_FOOT))
        y += GROUP_FOOT
    base = placed[-1].x + gap // 2 if placed else PAD
    width = max([base] + [_right_edge(r) for r in rows]) + PAD
    return Geometry(width, y + PAD // 2, placed, tuple(rows), tuple(frames))
