"""HTML and SVG for the sequence block.

The drawing is server-laid-out (`sequence_layout`) at 1:1 scale inside a scroll region,
so its text stays readable on a phone. It is complete without script. Below it an
ordered list states every step as text: that list is also the no-script, print and
copy form, and `static/sequence.js` links its items to the drawing's rows through
`data-step`. Colours come only from `--vd-*` tokens in `57-sequence.css`.
"""

from collections.abc import Mapping, Sequence

from varde_learn.docs.pages.blocks_render.common import as_list, count_noun, esc
from varde_learn.docs.pages.blocks_render.sequence_layout import (
    CHAR_W,
    HEAD_H,
    LINE_H,
    LOOP_W,
    PAD,
    Actor,
    Frame,
    Geometry,
    Row,
    clip_lines,
    layout,
)
from varde_learn.docs.pages.blocks_render.svg import copy_attr

Props = Mapping[str, object]
KIND_WORDS = {"call": "", "return": " (return)", "async": " (async)"}
HEAD_LEN = 9
HEAD_HALF = 5


def step_text(step: Props, labels: Mapping[str, str]) -> str:
    """`A to B: text`, `A to B (return): text`, `Note over A to B: text`."""
    source, target = labels[str(step["from"])], labels[str(step["to"])]
    kind, text = str(step.get("kind", "call")), str(step["text"])
    group = f" (group: {step['group']})" if "group" in step else ""
    if kind == "note":
        span = source if source == target else f"{source} to {target}"
        return f"Note over {span}: {text}{group}"
    return f"{source} to {target}{KIND_WORDS[kind]}: {text}{group}"


def _text(x: int, y: int, cls: str, body: str, anchor: str = "start") -> str:
    return (
        f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}">{esc(body)}</text>'
    )


def _lines(row: Row, top: int) -> str:
    return "".join(
        _text(row.text_x, top + n * LINE_H, "vd-sequence-text", line, row.anchor)
        for n, line in enumerate(row.lines)
    )


def _head(x: int, y: int, direction: int, filled: bool) -> str:
    back = x - direction * HEAD_LEN
    if filled:
        points = f"{x},{y} {back},{y - HEAD_HALF} {back},{y + HEAD_HALF}"
        return f'<polygon class="vd-sequence-head" points="{points}"/>'
    path = f"M{back} {y - HEAD_HALF} L{x} {y} L{back} {y + HEAD_HALF}"
    return f'<path class="vd-sequence-head-open" d="{path}"/>'


def _arrow(row: Row) -> str:
    cls = "vd-sequence-line" + (" vd-sequence-dashed" if row.kind == "return" else "")
    filled = row.kind == "call"
    if row.self_call:
        y, x = row.arrow_y, row.x1
        path = f"M{x} {y} H{x + LOOP_W} V{y + 14} H{x}"
        return f'<path class="{cls}" d="{path}"/>' + _head(x, y + 14, -1, filled)
    direction = 1 if row.x2 > row.x1 else -1
    line = f'<path class="{cls}" d="M{row.x1} {row.arrow_y} H{row.x2}"/>'
    return line + _head(row.x2, row.arrow_y, direction, filled)


def _row_body(row: Row) -> str:
    if row.kind == "note":
        box = (
            f'<rect class="vd-sequence-note-box" x="{row.x1}" y="{row.y + 4}" '
            f'width="{row.x2 - row.x1}" height="{row.h - 8}" rx="4"/>'
        )
        top = row.y + 4 + (row.h - 8 - LINE_H * len(row.lines)) // 2 + 12
        return box + _lines(row, top)
    return _lines(row, row.y + 14) + _arrow(row)


def _row(row: Row, width: int) -> str:
    hit = (
        f'<rect class="vd-sequence-hit" x="1" y="{row.y + 1}" '
        f'width="{width - 2}" height="{row.h - 2}"/>'
    )
    return (
        f'<g class="vd-sequence-row vd-sequence-{row.kind}" data-step="{row.index}">'
        f"{hit}{_row_body(row)}</g>"
    )


def _actor(actor: Actor, bottom: int) -> str:
    title = f"<title>{esc(actor.label)}</title>" if actor.truncated else ""
    texts = "".join(
        _text(actor.x, 18 + n * LINE_H, "vd-sequence-name", line, "middle")
        for n, line in enumerate(actor.lines)
    )
    life = f'<path class="vd-sequence-life" d="M{actor.x} {HEAD_H} V{bottom}"/>'
    box = (
        f'<rect class="vd-sequence-actor-box" x="{actor.box_x}" y="1" '
        f'width="{actor.box_w}" height="{HEAD_H - 2}" rx="4"/>'
    )
    return f'<g class="vd-sequence-actor">{title}{life}{box}{texts}</g>'


def _frame(frame: Frame, width: int) -> str:
    chars = max((width - PAD - 16) // CHAR_W, 4)
    label = clip_lines(frame.label, chars, 1)[0]
    cut = f"<title>{esc(frame.label)}</title>" if label != frame.label else ""
    return (
        f'<g class="vd-sequence-frame">{cut}'
        f'<rect class="vd-sequence-frame-box" x="{PAD // 2}" y="{frame.y}" '
        f'width="{width - PAD}" height="{frame.h}" rx="4"/>'
        + _text(PAD // 2 + 8, frame.y + 17, "vd-sequence-frame-label", label)
        + "</g>"
    )


def _drawing(geo: Geometry, label: str, desc: str) -> str:
    body = "".join(_frame(f, geo.width) for f in geo.frames)
    body += "".join(_actor(a, geo.height - PAD // 2) for a in geo.actors)
    body += "".join(_row(r, geo.width) for r in geo.rows)
    return (
        f'<svg class="vd-sequence-svg" viewBox="0 0 {geo.width} {geo.height}" '
        f'width="{geo.width}" height="{geo.height}" role="img" '
        f'aria-label="{esc(label)}" focusable="false">'
        f"<title>{esc(label)}</title><desc>{esc(desc)}</desc>{body}</svg>"
    )


def _steps_list(texts: Sequence[str]) -> str:
    items = "".join(
        f'<li class="vd-sequence-step" data-step="{n}">{esc(t)}</li>'
        for n, t in enumerate(texts)
    )
    return f'<ol class="vd-sequence-steps" aria-label="Steps">{items}</ol>'


def render_sequence(data: dict[str, object]) -> str:
    actors = [a for a in as_list(data["actors"]) if isinstance(a, dict)]
    steps = [s for s in as_list(data["steps"]) if isinstance(s, dict)]
    labels = {str(a["id"]): str(a["label"]) for a in actors}
    texts = [step_text(s, labels) for s in steps]
    title, desc = str(data.get("title", "")), str(data["desc"])
    name = title or "Sequence diagram"
    counts = f"{count_noun(len(steps), 'step', 'steps')}, " + count_noun(
        len(actors), "actor", "actors"
    )
    head = f'<h4 class="vb-title vd-sequence-title">{esc(title)}</h4>' if title else ""
    view = (
        f'<div class="vd-sequence-view" role="region" tabindex="0" '
        f'aria-label="{esc(name)} (scrollable)">'
        f"{_drawing(layout(actors, steps), name, desc)}</div>"
    )
    copy = "\n".join(f"{n}. {t}" for n, t in enumerate(texts, 1))
    return (
        f'<div class="vb sequence vd-sequence"{copy_attr(copy)}>{head}'
        f'<p class="vb-alt vd-sequence-summary">{esc(desc)} ({counts})</p>'
        f"{view}{_steps_list(texts)}</div>"
    )
