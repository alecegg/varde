"""HTML and SVG for the screen-flow block: wireframe screens joined by arrows.

Each screen is the wireframe frame drawing (`screens._frame_svg`) at half size, in a
tile with a numbered caption. The layout is computed on the server
(`screen_flow_layout`): ranks come from the diagram layout, a step joins neighbouring
ranks of one lane. Two drawings are emitted, across and down; CSS shows the second on
phones. Below them an ordered list gives each screen, its regions, its notes and
what comes next: the text alternative, the print form and the copy text.
`static/screen_flow.js` adds pan, zoom, selection and the notes panel.
"""

import re
import zlib
from collections.abc import Mapping, Sequence
from typing import Any

from varde_learn.docs.pages.blocks_render.common import (
    as_dict,
    as_list,
    count_noun,
    esc,
)
from varde_learn.docs.pages.blocks_render.diagram_layout import Box
from varde_learn.docs.pages.blocks_render.diagrams import _head, _text
from varde_learn.docs.pages.blocks_render.screen_flow_layout import (
    CAPTION_H,
    Band,
    Link,
    Plan,
    Screen,
    Tile,
    clip_lines,
    plan_flow,
)
from varde_learn.docs.pages.blocks_render.screens import _frame_svg, _notes, _used
from varde_learn.docs.pages.blocks_render.svg import copy_attr, svg_root

Props = Mapping[str, Any]
SCALE = 0.5
CAPTION_CW = 6.4
CAPTION_LINE = 13.0
LANE_TITLE_CHARS = 48
_SIZE = re.compile(r'<svg[^>]* width="(\d+)" height="(\d+)"')
_DIRECTIONS = (("LR", "across", "h"), ("TB", "down", "v"))


def _screens(data: Props) -> list[Props]:
    """Screens in document order; a repeated id keeps its first screen."""
    seen: dict[str, Props] = {}
    for screen in map(as_dict, as_list(data.get("screens"))):
        seen.setdefault(str(screen["id"]), screen)
    return list(seen.values())


def _steps(data: Props, ids: set[str]) -> list[tuple[str, str, str]]:
    steps = map(as_dict, as_list(data.get("steps")))
    return [
        (str(s["from"]), str(s["to"]), str(s.get("label", "")))
        for s in steps
        if str(s["from"]) in ids and str(s["to"]) in ids
    ]


def _lanes(data: Props, screens: Sequence[Props]) -> tuple[dict[str, int], list[str]]:
    """Lane index per screen id and the lane titles; one untitled lane by default."""
    lanes = [as_dict(x) for x in as_list(data.get("lanes"))]
    if not lanes:
        return {str(s["id"]): 0 for s in screens}, [""]
    of = {
        str(m): k for k, lane in enumerate(lanes) for m in as_list(lane.get("screens"))
    }
    return of, [str(lane["title"]) for lane in lanes]


def _natural(frame: Props) -> tuple[float, float]:
    svg = _frame_svg(dict(frame), str(frame.get("surface", "")), "size", "size")
    match = _SIZE.match(svg)
    return (float(match[1]), float(match[2])) if match else (0.0, 0.0)


def _plan(data: Props, direction: str) -> tuple[Plan, list[Props]]:
    screens = _screens(data)
    of, titles = _lanes(data, screens)
    ids = {str(s["id"]) for s in screens}
    sizes = {str(s["id"]): _natural(s) for s in screens}
    placed = [
        Screen(i, (w * SCALE, h * SCALE), of.get(i, 0)) for i, (w, h) in sizes.items()
    ]
    return plan_flow(placed, _steps(data, ids), titles, direction), screens


def _caption(tile: Tile, order: int, title: str) -> str:
    chars = max(4, int((tile.box.w - 8) // CAPTION_CW))
    lines = clip_lines(f"{order}. {title}", chars, 2)
    y = tile.box.y + tile.box.h - CAPTION_H / 2 + 2
    return _text(lines, "vd-sf-caption", tile.box.x + tile.box.w / 2, y, CAPTION_LINE)


def _tile(tile: Tile, order: int, screen: Props, uid: str, total: int) -> str:
    box, title = tile.box, str(screen["title"])
    frame = _frame_svg(dict(screen), str(screen.get("surface", "")), uid, title)
    at = f"translate({tile.thumb_at[0]:.1f} {tile.thumb_at[1]:.1f}) scale({SCALE:g})"
    said = f"{title}, screen {order} of {total}"
    return (
        f'<g class="vd-sf-screen" data-screen="{esc(screen["id"])}">'
        f"<title>{esc(said)}</title>"
        f'<rect class="vd-sf-tile" x="{box.x:.1f}" y="{box.y:.1f}" '
        f'width="{box.w:.1f}" height="{box.h:.1f}" rx="6"/>'
        f'<g class="vd-sf-thumb" aria-hidden="true" transform="{at}">{frame}</g>'
        f"{_caption(tile, order, title)}</g>"
    )


def _label(box: Box, lines: tuple[str, ...]) -> str:
    return (
        f'<rect class="vd-sf-label-bg" x="{box.x:.1f}" y="{box.y:.1f}" '
        f'width="{box.w:.1f}" height="{box.h:.1f}" rx="3"/>'
        + _text(lines, "vd-sf-edge-label", box.x + box.w / 2, box.y + box.h / 2, 14.0)
    )


def _link(link: Link, said: str) -> str:
    (x1, y1), (x2, y2) = link.points
    head = _head(link.points).replace("vd-head", "vd-sf-head")
    label = _label(link.label, link.lines) if link.label else ""
    return (
        f'<g class="vd-sf-edge"><title>{esc(said)}</title>'
        f'<path class="vd-sf-line" d="M{x1:.1f} {y1:.1f} L{x2:.1f} {y2:.1f}"/>'
        f"{head}{label}</g>"
    )


def _band(band: Band, title: str, down: bool) -> str:
    box = band.box
    if down:
        chars = max(4, int((box.w - 16) // CAPTION_CW))
        lines = clip_lines(title, chars, 2)
        x, y, anchor = box.x + 8, box.y + 12, ""
    else:
        lines = clip_lines(title, LANE_TITLE_CHARS, 1)
        x, y, anchor = box.x + 10, box.y + band.head / 2, ' dominant-baseline="central"'
    spans = "".join(
        f'<tspan x="{x:.1f}" y="{y + n * CAPTION_LINE:.1f}">{esc(line)}</tspan>'
        for n, line in enumerate(lines)
    )
    return (
        f'<g class="vd-sf-lane"><title>{esc(title)}</title>'
        f'<rect class="vd-sf-band" x="{box.x:.1f}" y="{box.y:.1f}" '
        f'width="{box.w:.1f}" height="{box.h:.1f}" rx="8"/>'
        f'<text class="vd-sf-lane-title"{anchor}>{spans}</text></g>'
    )


def _next_pairs(
    steps: Sequence[tuple[str, str, str]], titles: Mapping[str, str], me: str
) -> list[str]:
    """`Title (label)` for each step leaving `me`, in step order."""
    return [
        titles[b] + (f" ({label})" if label else "") for a, b, label in steps if a == me
    ]


def _drawing(data: Props, direction: str, name: str, desc: str, tag: str) -> str:
    plan, screens = _plan(data, direction)
    by_id = {str(s["id"]): s for s in screens}
    ids = set(by_id)
    steps = _steps(data, ids)
    _, titles = _lanes(data, screens)
    seed = zlib.crc32(repr(sorted(data.items())).encode())
    down = direction == "TB"
    body = "".join(_band(b, titles[b.index], down) for b in plan.bands)
    for link in plan.links:
        said = f"{by_id[link.source]['title']} to {by_id[link.target]['title']}"
        label = next(
            (x for a, b, x in steps if (a, b) == (link.source, link.target)), ""
        )
        body += _link(link, said + (f" on {label}" if label else ""))
    body += "".join(
        _tile(t, n, by_id[t.id], f"sf{seed:08x}{tag}{n}", len(screens))
        for n, t in enumerate(plan.tiles, 1)
    )
    svg = svg_root(name, desc, (0.0, 0.0, plan.width, plan.height), body, "vd-sf-svg")
    return svg.replace(
        "<svg ", f'<svg width="{plan.width:g}" height="{plan.height:g}" ', 1
    )


def _regions(screen: Props) -> str:
    names = [str(as_dict(screen["regions"])[k]) for k in _used(dict(screen))]
    return f"{count_noun(len(names), 'region', 'regions')}: {', '.join(names)}"


def _item_parts(data: Props) -> list[tuple[Props, str, str, str]]:
    """(screen, lane suffix, region summary, next text) in reading order."""
    plan, screens = _plan(data, "LR")
    by_id = {str(s["id"]): s for s in screens}
    of, lanes = _lanes(data, screens)
    titles = {i: str(s["title"]) for i, s in by_id.items()}
    steps = _steps(data, set(by_id))
    out = []
    for tile in plan.tiles:
        screen = by_id[tile.id]
        lane = f" ({lanes[of[tile.id]]} lane)" if data.get("lanes") else ""
        follow = _next_pairs(steps, titles, tile.id)
        out.append(
            (
                screen,
                lane,
                _regions(screen),
                "next: " + ", ".join(follow) if follow else "end of flow",
            )
        )
    return out


def _notes_list(screen: Props) -> str:
    regions = as_dict(screen["regions"])
    items = "".join(
        f'<li value="{n}" class="vd-sf-note"><strong>{esc(regions[r])}</strong>: '
        f"{esc(text)}</li>"
        for n, r, text in _notes(dict(screen))
    )
    return f'<ol class="vd-sf-notes" aria-label="Notes">{items}</ol>' if items else ""


def _item(parts: tuple[Props, str, str, str]) -> str:
    screen, lane, regions, follow = parts
    return (
        f'<li class="vd-sf-item" data-screen="{esc(screen["id"])}">'
        f'<strong class="vd-sf-name">{esc(screen["title"])}</strong>{esc(lane)}: '
        f'<span class="vd-sf-regions">{esc(regions)}</span>; '
        f'<span class="vd-sf-next">{esc(follow)}</span>{_notes_list(screen)}</li>'
    )


def alternative_lines(data: Props) -> list[str]:
    """`Title: 3 regions: a, b; next: Other (label)`, one per screen, in order."""
    return [f"{s['title']}{lane}: {r}; {f}" for s, lane, r, f in _item_parts(data)]


def _summary(data: Props) -> str:
    screens = _screens(data)
    steps = _steps(data, {str(s["id"]) for s in screens})
    parts = [
        count_noun(len(screens), "screen", "screens"),
        count_noun(len(steps), "step", "steps"),
    ]
    lanes = as_list(data.get("lanes"))
    if lanes:
        parts.append(count_noun(len(lanes), "lane", "lanes"))
    return ", ".join(parts)


def copy_text(data: Props) -> str:
    """Plain text for the Copy entry: the title, then the numbered screens."""
    head = f"{data.get('title', 'Screen flow')} (screen flow, {_summary(data)})"
    lines = [f"{n}. {line}" for n, line in enumerate(alternative_lines(data), 1)]
    return "\n".join([head, *lines])


def _view(svg: str, name: str, cls: str) -> str:
    label = f'role="region" tabindex="0" aria-label="{esc(name)} (scrollable)"'
    return f'<div class="vd-sf-view {cls}" {label}>{svg}</div>'


def render_screen_flow(data: dict[str, object]) -> str:
    title, desc = str(data.get("title", "")), str(data.get("desc", "Screen flow"))
    name = title or "Screen flow"
    head = f'<h4 class="vb-title vd-sf-title">{esc(title)}</h4>' if title else ""
    views = "".join(
        _view(
            _drawing(data, direction, name, f"{desc}, {way}", tag), name, f"vd-sf-{way}"
        )
        for direction, way, tag in _DIRECTIONS
    )
    items = "".join(_item(p) for p in _item_parts(data))
    summary = f'<p class="vb-alt vd-sf-summary">{esc(desc)} ({_summary(data)})</p>'
    listing = f'<ol class="vd-sf-list" aria-label="Screens in order">{items}</ol>'
    root = f'<div class="vb screen-flow vd-sf"{copy_attr(copy_text(data))}>'
    return f'{root}{head}{summary}<div class="vd-sf-views">{views}</div>{listing}</div>'
