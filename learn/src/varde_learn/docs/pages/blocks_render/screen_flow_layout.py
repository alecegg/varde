"""Pure layout for the screen-flow block: ranks, lanes, tiles and straight connectors.

Ranks come from the diagram layout (`assign_layers`). A rank is a column when the
flow runs across (`LR`) and a row when it runs down (`TB`); a lane is the other
axis. Every step joins neighbouring ranks of one lane, so a connector is one
straight segment from a tile edge to the next tile edge. Labels sit in the open
gap beside the connector. No I/O, no HTML.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from varde_learn.docs.pages.blocks_render.diagram_layout import Box, assign_layers
from varde_learn.docs.pages.blocks_render.svg import wrap_text

Size = tuple[float, float]
Point = tuple[float, float]

MARGIN = 12.0
BAND_PAD = 10.0
INSET = 4.0
MIN_TILE_W = 96.0
CAPTION_H = 34.0
MIN_LANE_DOWN = 112.0
GAP_ACROSS, GAP_DOWN = 96.0, 72.0
LANE_GAP = 20.0
HEAD_ACROSS, HEAD_DOWN = 26.0, 40.0
LABEL_CHARS, LABEL_LINES, LABEL_CW, LABEL_LH, LABEL_PAD = 12, 3, 6.4, 14.0, 4.0
LABEL_CLIP = 40


@dataclass(frozen=True)
class Screen:
    id: str
    thumb: Size  # drawn size of the wireframe thumbnail
    lane: int


@dataclass(frozen=True)
class Tile:
    id: str
    box: Box  # thumbnail, caption and a thin frame
    thumb_at: Point


@dataclass(frozen=True)
class Link:
    source: str
    target: str
    points: tuple[Point, Point]
    label: Box | None
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Band:
    index: int
    box: Box
    head: float  # height (LR) or width-independent strip (TB) kept for the title


@dataclass(frozen=True)
class Plan:
    width: float
    height: float
    tiles: tuple[Tile, ...]  # in reading order: lane, then rank, then document order
    links: tuple[Link, ...]
    bands: tuple[Band, ...]  # empty when the lanes are not titled


def clip_lines(text: str, chars: int, count: int) -> tuple[str, ...]:
    """The text wrapped to `chars` columns, at most `count` lines, a cut marked `…`."""
    lines = wrap_text(text, chars)
    if len(lines) <= count:
        return tuple(lines)
    kept = lines[:count]
    kept[-1] = kept[-1][: max(chars - 1, 1)] + "…"
    return tuple(kept)


def tile_size(thumb: Size) -> Size:
    return max(thumb[0] + 2 * INSET, MIN_TILE_W), thumb[1] + 2 * INSET + CAPTION_H


def label_lines(label: str) -> tuple[str, ...]:
    return clip_lines(label[:LABEL_CLIP], LABEL_CHARS, LABEL_LINES) if label else ()


def label_size(lines: Sequence[str]) -> Size:
    if not lines:
        return 0.0, 0.0
    return max(len(x) for x in lines) * LABEL_CW + 2 * LABEL_PAD, len(
        lines
    ) * LABEL_LH + LABEL_PAD


def reading_order(screens: Sequence[Screen], ranks: dict[str, int]) -> list[Screen]:
    order = {s.id: n for n, s in enumerate(screens)}
    return sorted(screens, key=lambda s: (s.lane, ranks[s.id], order[s.id]))


def _spans(extents: Sequence[float], gap: float, start: float) -> list[float]:
    starts, at = [], start
    for extent in extents:
        starts.append(at)
        at += extent + gap
    return starts


def _link(a: Box, b: Box, centre: float, label: str, down: bool) -> Link:
    lines = label_lines(label)
    w, h = label_size(lines)
    if down:
        p1, p2 = (centre, a.y + a.h), (centre, b.y)
        mid = (p1[1] + p2[1]) / 2
        box = Box(centre + 6, mid - h / 2, w, h)
    else:
        p1, p2 = (a.x + a.w, centre), (b.x, centre)
        mid = (p1[0] + p2[0]) / 2
        box = Box(mid - w / 2, centre - LABEL_PAD - h, w, h)
    return Link("", "", (p1, p2), box if lines else None, lines)


def plan_flow(
    screens: Sequence[Screen],
    steps: Sequence[tuple[str, str, str]],
    lane_titles: Sequence[str],
    direction: str,
) -> Plan:
    """Tiles, connectors and lane bands; `direction` is `LR` (across) or `TB` (down)."""
    down = direction == "TB"
    ids = [s.id for s in screens]
    ranks = assign_layers(ids, [(a, b) for a, b, _ in steps])
    count = max(ranks.values(), default=0) + 1
    sizes = {s.id: tile_size(s.thumb) for s in screens}
    along, across = (1, 0) if down else (0, 1)  # index into a (w, h) size
    lanes = max([s.lane for s in screens], default=0) + 1
    titled = any(lane_titles)
    head = (HEAD_DOWN if down else HEAD_ACROSS) if titled else 0.0
    rank_ext = [
        max((sizes[s.id][along] for s in screens if ranks[s.id] == r), default=0.0)
        for r in range(count)
    ]
    floor = MIN_LANE_DOWN if down else 0.0
    lane_ext = [
        max(
            [
                floor,
                *(sizes[s.id][across] + 2 * BAND_PAD for s in screens if s.lane == k),
            ]
        )
        for k in range(lanes)
    ]
    gap = GAP_DOWN if down else GAP_ACROSS
    main0 = MARGIN + BAND_PAD + (head if down else 0.0)
    main_at = _spans(rank_ext, gap, main0)
    main_len = main_at[-1] + rank_ext[-1] - main0
    lane_head = 0.0 if down else head
    lane_at = _spans([e + lane_head for e in lane_ext], LANE_GAP, MARGIN)
    centres = [lane_at[k] + lane_head + lane_ext[k] / 2 for k in range(lanes)]
    cross_end = lane_at[-1] + lane_head + lane_ext[-1]
    main_end = main0 + main_len + BAND_PAD
    boxes: dict[str, Box] = {}
    for s in screens:
        w, h = sizes[s.id]
        main = main_at[ranks[s.id]] + (rank_ext[ranks[s.id]] - sizes[s.id][along]) / 2
        cross = centres[s.lane] - sizes[s.id][across] / 2
        boxes[s.id] = Box(cross, main, w, h) if down else Box(main, cross, w, h)
    links = []
    for a, b, label in steps:
        lane = next(s.lane for s in screens if s.id == a)
        made = _link(boxes[a], boxes[b], centres[lane], label, down)
        links.append(Link(a, b, made.points, made.label, made.lines))
    tiles = tuple(
        Tile(
            s.id,
            boxes[s.id],
            (boxes[s.id].x + (boxes[s.id].w - s.thumb[0]) / 2, boxes[s.id].y + INSET),
        )
        for s in reading_order(screens, ranks)
    )
    bands: tuple[Band, ...] = ()
    if titled and down:
        bands = tuple(
            Band(k, Box(lane_at[k], MARGIN, lane_ext[k], main_end - MARGIN), head)
            for k in range(lanes)
        )
    if titled and not down:
        bands = tuple(
            Band(
                k, Box(MARGIN, lane_at[k], main_end - MARGIN, head + lane_ext[k]), head
            )
            for k in range(lanes)
        )
    width, height = (cross_end, main_end) if down else (main_end, cross_end)
    return Plan(width + MARGIN, height + MARGIN, tiles, tuple(links), bands)
