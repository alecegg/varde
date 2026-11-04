"""HTML for wireframe and ui-states blocks.

A wireframe is a closed grid-region description drawn as SVG on the server: an
optional device frame (browser, phone or tablet), regions with a hatch pattern per
kind, numbered note pins, a notes list under the frame and a region table as the
text alternative. `static/wireframe.js` adds pan, zoom and region selection.
"""

import zlib

from varde_learn.docs.pages.blocks_render.common import (
    as_dict,
    as_list,
    badge,
    card,
    data_scroll,
    esc,
)
from varde_learn.docs.pages.blocks_render.svg import copy_attr, wrap_text

Frame = dict[str, object]
Bounds = tuple[int, int, int, int]

CELL_W, CELL_H, PAD = 56, 49, 4  # a one-cell region is at least 52 x 45 CSS px
_REGION_CLASSES = 6
_LINE_H, _CHAR_W = 13, 7.5  # wide enough that a label stays inside its region
_PLAIN = (10, 10, 10, 10)
_SURFACE_MARGINS = {
    "browser": (8, 40, 8, 8),
    "phone": (16, 30, 16, 30),
    "tablet": (18, 18, 18, 30),
}
# kind -> (patternTransform, mark): six hatches that differ by shape, not colour
_KIND_PATTERN = {
    "nav": ("rotate(45)", '<path d="M0 4H8"/>'),
    "text": ("", '<path d="M0 4H4"/>'),
    "media": ("rotate(45)", '<path d="M0 4H8M4 0V8"/>'),
    "input": ("rotate(90)", '<path d="M0 4H8"/>'),
    "action": ("", '<circle cx="4" cy="4" r="1.4"/>'),
    "list": ("rotate(-45)", '<path d="M0 4H8"/>'),
}


def _bounds(rows: list[str], letter: str) -> Bounds:
    hits = [
        (r, c) for r, row in enumerate(rows) for c, ch in enumerate(row) if ch == letter
    ]
    rs, cs = [h[0] for h in hits], [h[1] for h in hits]
    return min(rs), min(cs), max(rs), max(cs)


def _rows(frame: Frame) -> list[str]:
    return [r for r in as_list(frame["grid"]) if isinstance(r, str)]


def _used(frame: Frame) -> list[str]:
    rows = _rows(frame)
    return [k for k in as_dict(frame["regions"]) if any(k in row for row in rows)]


def _kind(frame: Frame, letter: str) -> str:
    return str(as_dict(frame.get("kinds")).get(letter, ""))


def _notes(frame: Frame) -> list[tuple[int, str, str]]:
    """(number, region letter, text) in props order, numbered from 1."""
    used = set(_used(frame))
    notes = [as_dict(n) for n in as_list(frame.get("notes"))]
    return [
        (n, str(note["region"]), str(note["text"]))
        for n, note in enumerate(notes, 1)
        if str(note.get("region")) in used
    ]


def _pattern(uid: str, kind: str) -> str:
    transform, mark = _KIND_PATTERN[kind]
    attr = f' patternTransform="{transform}"' if transform else ""
    return (
        f'<pattern id="vw-{uid}-{kind}" class="vw-k-{kind}" width="8" height="8" '
        f'patternUnits="userSpaceOnUse"{attr}>{mark}</pattern>'
    )


def _tspans(lines: list[tuple[str, str]], cx: float, top: float) -> str:
    """One `<text>` per line (class, text), the block centred on `top`."""
    out = []
    for n, (cls, text) in enumerate(lines):
        y = top + n * _LINE_H
        out.append(
            f'<text class="{cls}" x="{cx:g}" y="{y:g}" text-anchor="middle">'
            f"{esc(text)}</text>"
        )
    return "".join(out)


def _label_lines(label: str, kind: str, w: float, h: float) -> list[tuple[str, str]]:
    room = max(1, int((h - 8) // _LINE_H))
    chars = max(4, int((w - 10) // _CHAR_W))
    lines = wrap_text(label, chars)
    extra = 1 if kind and len(lines) < room else 0
    shown = lines[: room - extra]
    if len(shown) < len(lines):
        shown[-1] = shown[-1][: max(chars - 1, 1)] + "…"
    out = [("vw-region-label", t) for t in shown]
    return out + ([("vw-kind", f"[{kind}]")] if extra else [])


def _pins(numbers: list[int], x: float, y: float, w: float) -> str:
    """Numbered pins along the top edge, squeezed so they stay inside the region."""
    gap = 24 if len(numbers) < 2 else min(24, (w - 28) / (len(numbers) - 1))
    return "".join(
        f'<g class="vw-pin" aria-hidden="true"><circle cx="{x + 14 + k * gap:g}" '
        f'cy="{y + 14:g}" r="10"/><text x="{x + 14 + k * gap:g}" y="{y + 14:g}" '
        f'text-anchor="middle" dominant-baseline="central">{n}</text></g>'
        for k, n in enumerate(numbers)
    )


def _region(
    frame: Frame, letter: str, index: int, uid: str, origin: tuple[int, int]
) -> str:
    r0, c0, r1, c1 = _bounds(_rows(frame), letter)
    x, y = origin[0] + c0 * CELL_W + PAD, origin[1] + r0 * CELL_H + PAD
    w, h = (c1 - c0 + 1) * CELL_W - PAD, (r1 - r0 + 1) * CELL_H - PAD
    label = str(as_dict(frame["regions"])[letter])
    kind = _kind(frame, letter)
    hatch = ""
    if kind:
        hatch = (
            f'<rect class="vw-hatch" x="{x}" y="{y}" width="{w}" height="{h}" '
            f'rx="4" fill="url(#vw-{uid}-{kind})"/>'
        )
    numbers = [n for n, region, _ in _notes(frame) if region == letter]
    title = f"{label} ({kind})" if kind else label
    lines = _label_lines(label, kind, w, h)
    top = y + h / 2 - (len(lines) - 1) * _LINE_H / 2 + 4 + (8 if numbers else 0)
    return (
        f'<g class="vw-region vb-r{index % _REGION_CLASSES}" '
        f'data-region="{esc(letter)}">'
        f"<title>{esc(title)}</title>"
        f'<rect class="vw-box vb-region vb-r{index % _REGION_CLASSES}" x="{x}" y="{y}" '
        f'width="{w}" height="{h}" rx="4"/>{hatch}'
        f"{_tspans(lines, x + w / 2, top)}{_pins(numbers, x, y, w)}</g>"
    )


def _rect(cls: str, x: float, y: float, w: float, h: float, rx: float) -> str:
    return (
        f'<rect class="{cls}" x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" '
        f'rx="{rx:g}"/>'
    )


def _circle(cls: str, cx: float, cy: float, r: float) -> str:
    return f'<circle class="{cls}" cx="{cx:g}" cy="{cy:g}" r="{r:g}"/>'


def _device(surface: str, width: float, height: float) -> str:
    """Bezel and chrome of a browser, phone or tablet, drawn from tokens only."""
    if not surface:
        return ""
    mid = width / 2
    radius = {"browser": 8, "phone": 28, "tablet": 18}[surface]
    shapes = [_rect("vw-bezel", 1, 1, width - 2, height - 2, radius)]
    if surface == "browser":
        shapes += [_circle("vw-dot", 20 + 14 * i, 20, 4) for i in range(3)]
        if width > 120:
            shapes.append(_rect("vw-bar", 70, 11, width - 84, 18, 9))
    if surface == "phone":
        shapes.append(_rect("vw-bar", mid - 18, 10, 36, 6, 3))
        shapes.append(_rect("vw-bar", mid - 22, height - 16, 44, 4, 2))
    if surface == "tablet":
        shapes.append(_circle("vw-dot", mid, 9, 3))
        shapes.append(_circle("vw-bar", mid, height - 15, 7))
    return f'<g class="vw-device" aria-hidden="true">{"".join(shapes)}</g>'


def _frame_svg(frame: Frame, surface: str, uid: str, title: str) -> str:
    rows = _rows(frame)
    left, top, right, bottom = _SURFACE_MARGINS.get(surface, _PLAIN)
    cols = max((len(r) for r in rows), default=1)
    width = left + cols * CELL_W + PAD + right
    height = top + max(len(rows), 1) * CELL_H + PAD + bottom
    kinds = sorted({_kind(frame, k) for k in _used(frame)} - {""})
    defs = f"<defs>{''.join(_pattern(uid, k) for k in kinds)}</defs>" if kinds else ""
    inner_w, inner_h = width - left - right, height - top - bottom
    screen = _rect("vw-screen", left - 2, top - 2, inner_w + 4, inner_h + 4, 0)
    screen = screen if surface else ""
    shapes = "".join(
        _region(frame, k, n, uid, (left, top)) for n, k in enumerate(_used(frame))
    )
    where = f"{surface} " if surface else ""
    desc = f"{where}wireframe with {len(_used(frame))} regions"
    names = ", ".join(str(as_dict(frame["regions"])[k]) for k in _used(frame))
    return (
        f'<svg class="vb-wire vw-svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">'
        f"<title>{esc(title)}</title><desc>{esc(desc + ': ' + names)}</desc>"
        f"{defs}{_device(surface, width, height)}{screen}{shapes}</svg>"
    )


def _position(rows: list[str], letter: str) -> str:
    r0, c0, r1, c1 = _bounds(rows, letter)
    span = lambda a, b: f"{a + 1}" if a == b else f"{a + 1}-{b + 1}"  # noqa: E731
    return f"rows {span(r0, r1)}, columns {span(c0, c1)}"


def _region_rows(frame: Frame) -> list[list[object]]:
    regions = as_dict(frame["regions"])
    notes = _notes(frame)
    rows = _rows(frame)
    return [
        [
            regions[k],
            _kind(frame, k) or "none",
            _position(rows, k),
            "; ".join(f"{n}. {text}" for n, region, text in notes if region == k)
            or "none",
        ]
        for k in _used(frame)
    ]


def _notes_list(frame: Frame) -> str:
    regions = as_dict(frame["regions"])
    items = "".join(
        f'<li value="{n}" class="vw-note" data-region="{esc(region)}">'
        f"<strong>{esc(regions[region])}</strong>: {esc(text)}</li>"
        for n, region, text in _notes(frame)
    )
    return f'<ol class="vw-notes" aria-label="Notes">{items}</ol>' if items else ""


def _region_table(frame: Frame, alt: str, summary: str) -> str:
    """The text alternative; not `vb-table`, so table.js adds no sort or sticky head."""
    head = "".join(f"<th>{h}</th>" for h in ("Region", "Kind", "Position", "Notes"))
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>"
        for row in _region_rows(frame)
    )
    grid = (
        f'<table class="vb-data-grid"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )
    grid = data_scroll(grid, summary)
    return (
        f'<details class="vb-data"><summary>{esc(summary)}</summary>'
        f'<p class="vb-alt">{esc(alt)}</p>{grid}</details>'
    )


def _figure(frame: Frame, data: dict[str, object], caption: str, uid: str) -> str:
    surface = str(data.get("surface", ""))
    base = str(data.get("title", "Wireframe"))
    title = f"{base}: {caption.lower()}" if caption else base
    head = f"<figcaption>{esc(caption)}</figcaption>" if caption else ""
    name = f'role="region" tabindex="0" aria-label="{esc(title)} (scrollable)"'
    view = f'<div class="vw-view" {name}>{_frame_svg(frame, surface, uid, title)}</div>'
    summary = f"{caption}: regions as text" if caption else "Regions as text"
    table = _region_table(frame, f"{len(_used(frame))} regions", summary)
    return f'<figure class="vw-fig">{head}{view}{_notes_list(frame)}{table}</figure>'


def _frames(data: dict[str, object]) -> list[tuple[str, Frame]]:
    after = data.get("compare")
    if not isinstance(after, dict):
        return [("", data)]
    return [("Before", data), ("After", after)]


def copy_text(data: dict[str, object]) -> str:
    """Plain text for the Copy entry: each frame's regions, then its notes."""
    surface = str(data.get("surface", "")) + " " if data.get("surface") else ""
    lines = [f"{data.get('title', 'Wireframe')} ({surface}wireframe)"]
    for caption, frame in _frames(data):
        regions = as_dict(frame["regions"])
        lines.append(f"{caption}:" if caption else "Regions:")
        for k in _used(frame):
            kind = _kind(frame, k)
            lines.append(f"- {regions[k]}" + (f" [{kind}]" if kind else ""))
        notes = _notes(frame)
        if notes:
            lines.append("Notes:")
        lines += [f"{n}. {regions[r]}: {text}" for n, r, text in notes]
    return "\n".join(lines)


def render_wireframe(data: dict[str, object]) -> str:
    seed = zlib.crc32(repr(sorted(data.items())).encode())
    figures = "".join(
        _figure(frame, data, caption, f"{seed:08x}{n}")
        for n, (caption, frame) in enumerate(_frames(data))
    )
    compare = " vw-compare" if isinstance(data.get("compare"), dict) else ""
    unit = f'data-min-unit="{min(CELL_W, CELL_H) - PAD:g}"'
    heading = esc(data["title"]) if "title" in data else ""
    body = f'<div class="vw-frames{compare}" {unit}>{figures}</div>'
    root = f'<div class="vb wireframe"{copy_attr(copy_text(data))}>'
    return f"{root}{card(heading, body)}</div>"


def _tile(name: str, state: dict[str, object]) -> str:
    if "na" in state:
        body = f"{badge('n/a', 'vb-na')} <span>{esc(state['na'])}</span>"
    else:
        body = f"<p>{esc(state['shows'])}</p>"
    return (
        f'<div class="vb-state vb-state-{esc(name)}"><h5>{esc(name)}</h5>{body}</div>'
    )


def ui_states_copy(data: dict[str, object]) -> str:
    lines = [f"{data.get('screen', 'Screen')} (ui-states)"]
    for name, state in data.items():
        if not isinstance(state, dict):
            continue
        said = f"n/a, {state['na']}" if "na" in state else state["shows"]
        lines.append(f"- {name}: {said}")
    return "\n".join(lines)


def render_ui_states(data: dict[str, object]) -> str:
    tiles = "".join(_tile(n, s) for n, s in data.items() if isinstance(s, dict))
    heading = esc(data["screen"]) if "screen" in data else ""
    layout = f' data-layout="{esc(data["layout"])}"' if "layout" in data else ""
    count = sum(isinstance(v, dict) for v in data.values())
    alt = f'<p class="vb-alt">{count} states of the screen</p>'
    grid = f'{alt}<div class="vb-grid"{layout}>{tiles}</div>'
    return (
        f'<div class="vb ui-states"{copy_attr(ui_states_copy(data))}>'
        f"{card(heading, grid)}</div>"
    )
