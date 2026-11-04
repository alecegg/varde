"""Grid placement and orthogonal routing for the data-model `graph` layout.

Pure and deterministic: entities fill a grid row by row, every box is as tall as
its visible field rows, and a relation runs along the empty channels between
rows and columns, so a line never crosses a box. Coordinates are SVG units.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

BOX_W = 220.0
HEAD_H = 30.0
ROW_H = 18.0
PAD_B = 10.0
GAP_X = 64.0
GAP_Y = 56.0
MARGIN_X = 40.0
MARGIN_Y = 44.0
MAX_COLS = 3
MAX_FIELD_ROWS = 6
LOOP = 16.0
LANES = 4
Point = tuple[float, float]


@dataclass(frozen=True)
class Box:
    index: int
    col: int
    grid_row: int
    x: float
    y: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + BOX_W / 2

    @property
    def bottom(self) -> float:
        return self.y + self.h


@dataclass(frozen=True)
class Grid:
    boxes: tuple[Box, ...]
    cols: int
    row_top: tuple[float, ...]
    row_bottom: tuple[float, ...]
    width: float
    height: float


def visible_rows(field_count: int) -> tuple[int, int]:
    """`(shown, hidden)` field rows of a box; the rest read "+n more"."""
    shown = min(max(field_count, 1), MAX_FIELD_ROWS)
    return shown, max(field_count - shown, 0)


def box_height(field_count: int) -> float:
    shown, hidden = visible_rows(field_count)
    return HEAD_H + (shown + (1 if hidden else 0)) * ROW_H + PAD_B


def place(field_counts: list[int]) -> Grid:
    """Row-major grid of up to `MAX_COLS` columns; rows fit their tallest box."""
    cols = max(min(len(field_counts), MAX_COLS), 1)
    heights = [box_height(n) for n in field_counts]
    bands = [heights[i : i + cols] for i in range(0, len(heights), cols)]
    row_top: list[float] = []
    row_bottom: list[float] = []
    y = MARGIN_Y
    for band in bands:
        row_top.append(y)
        row_bottom.append(y + max(band))
        y += max(band) + GAP_Y
    boxes = tuple(
        Box(i, i % cols, i // cols, _col_x(i % cols), row_top[i // cols], h)
        for i, h in enumerate(heights)
    )
    width = 2 * MARGIN_X + cols * BOX_W + (cols - 1) * GAP_X
    height = row_bottom[-1] + MARGIN_Y if row_bottom else 2 * MARGIN_Y
    return Grid(boxes, cols, tuple(row_top), tuple(row_bottom), width, height)


def _col_x(col: int) -> float:
    return MARGIN_X + col * (BOX_W + GAP_X)


def _gap_x(grid: Grid, gap: int) -> float:
    """Middle of the vertical channel right of column `gap` (-1 is the left margin)."""
    if gap < 0:
        return MARGIN_X / 2
    if gap >= grid.cols - 1:
        return _col_x(grid.cols - 1) + BOX_W + MARGIN_X / 2
    return _col_x(gap) + BOX_W + GAP_X / 2


def _channel_gap(grid: Grid, a: Box, b: Box) -> int:
    """The column gap an elbow uses: the one beside `a`, on the side facing `b`."""
    if b.col > a.col:
        return a.col
    if b.col < a.col:
        return a.col - 1
    return a.col if a.col < grid.cols - 1 else a.col - 1


def _simplified(points: list[Point]) -> list[Point]:
    """Drop repeated points and the middle of three collinear ones."""
    unique = [p for i, p in enumerate(points) if i == 0 or p != points[i - 1]]
    kept = unique[:1]
    for i in range(1, len(unique) - 1):
        (x0, y0), (x1, y1), (x2, y2) = kept[-1], unique[i], unique[i + 1]
        if (x0 == x1 == x2) or (y0 == y1 == y2):
            continue
        kept.append(unique[i])
    return kept + unique[1:][-1:] if len(unique) > 1 else unique


def _loop(a: Box) -> list[Point]:
    right = a.x + BOX_W
    top, low = a.y + HEAD_H / 2 - 7, a.y + HEAD_H / 2 + 7
    return [(right, top), (right + LOOP, top), (right + LOOP, low), (right, low)]


def route(grid: Grid, a: Box, b: Box, lane: int) -> list[Point]:
    """Points of a relation from the edge of `a` to the edge of `b`.

    `lane` shifts the shared channels so relations through one gap stay apart.
    """
    if a.index == b.index:
        return _loop(a)
    off = (lane % LANES) * 5 - 7
    if a.grid_row == b.grid_row and abs(a.col - b.col) == 1:
        y = a.y + HEAD_H / 2 + off * 0.8
        start = a.x + BOX_W if b.col > a.col else a.x
        end = b.x if b.col > a.col else b.x + BOX_W
        return [(start, y), (end, y)]
    down = b.grid_row > a.grid_row
    above = a.grid_row == b.grid_row
    if down:
        first = grid.row_bottom[a.grid_row] + GAP_Y / 2 + off
        second = grid.row_top[b.grid_row] - GAP_Y / 2 + off
        start_y, end_y = a.bottom, b.y
    elif above:
        first = second = grid.row_top[a.grid_row] - GAP_Y / 2 + off
        start_y, end_y = a.y, b.y
    else:
        first = grid.row_top[a.grid_row] - GAP_Y / 2 + off
        second = grid.row_bottom[b.grid_row] + GAP_Y / 2 + off
        start_y, end_y = a.y, b.bottom
    gx = _gap_x(grid, _channel_gap(grid, a, b)) + off
    if above:
        return _simplified(
            [(a.cx + off, start_y), (a.cx + off, first), (b.cx + off, second),
             (b.cx + off, end_y)]
        )  # fmt: skip
    return _simplified(
        [(a.cx + off, start_y), (a.cx + off, first), (gx, first), (gx, second),
         (b.cx + off, second), (b.cx + off, end_y)]
    )  # fmt: skip


def label_point(points: list[Point], at_start: bool) -> Point:
    """Where a cardinality label sits: just off the endpoint, beside the line."""
    (x0, y0), (x1, y1) = (
        (points[0], points[1]) if at_start else (points[-1], points[-2])
    )
    dx = (x1 > x0) - (x1 < x0)
    dy = (y1 > y0) - (y1 < y0)
    return (x0 + dx * 12 + (-dy) * 9, y0 + dy * 12 + dx * 9)


def edges_cross_boxes(grid: Grid, points: list[Point]) -> bool:
    """True when a segment passes through the inside of any box (a test aid)."""
    for (x0, y0), (x1, y1) in pairwise(points):
        lo_x, hi_x = sorted((x0, x1))
        lo_y, hi_y = sorted((y0, y1))
        for box in grid.boxes:
            inside_x = lo_x < box.x + BOX_W and hi_x > box.x
            inside_y = lo_y < box.bottom and hi_y > box.y
            if inside_x and inside_y:
                return True
    return False
