"""Layered graph layout: pure, deterministic, cycle-safe, no I/O.

Steps: cut cycles (DFS back edges are drawn reversed), give each node a layer
(longest path), insert a slot ("dummy") per layer an edge crosses so long edges
stay out of nodes, order each layer by neighbour averages, then place lanes
(one per group, so group frames never interleave) and route each edge through
the empty gaps between layer bands. Coordinates: `cross` runs across layers,
`ext` along them; direction TB maps ext to y, LR maps ext to x.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from varde_learn.docs.pages.blocks_render.svg import wrap_text

CHAR_W = 7.0
LINE_H = 16.0
WRAP = 18
PAD_X, PAD_Y = 14.0, 9.0
MIN_W, MIN_H = 64.0, 48.0
NODE_GAP = 28.0
LANE_GAP = 28.0
LAYER_GAP = 44.0
DUMMY = 14.0
LOOP = 18.0
PARALLEL = 10.0
FRAME_PAD = 14.0
FRAME_HEAD = 48.0
MARGIN = 16.0
LABEL_CW, LABEL_LH, LABEL_WRAP = 6.4, 14.0, 14
SWEEPS = 4
Point = tuple[float, float]


@dataclass(frozen=True)
class NodeSpec:
    id: str
    label: str
    shape: str = "box"
    lane: str = ""


@dataclass(frozen=True)
class EdgeSpec:
    source: str
    target: str
    label: str = ""
    style: str = "solid"


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    def grown(self, by: float) -> Box:
        return Box(self.x - by, self.y - by, self.w + 2 * by, self.h + 2 * by)

    def overlaps(self, other: Box) -> bool:
        return (
            self.x < other.x + other.w
            and other.x < self.x + self.w
            and self.y < other.y + other.h
            and other.y < self.y + self.h
        )


@dataclass(frozen=True)
class PlacedNode:
    spec: NodeSpec
    box: Box
    lines: tuple[str, ...]


@dataclass(frozen=True)
class PlacedEdge:
    spec: EdgeSpec
    points: tuple[Point, ...]
    label_lines: tuple[str, ...]
    label_box: Box | None


@dataclass(frozen=True)
class PlacedFrame:
    lane: str
    label: str
    box: Box


@dataclass(frozen=True)
class Layout:
    width: float
    height: float
    nodes: tuple[PlacedNode, ...]
    edges: tuple[PlacedEdge, ...]
    frames: tuple[PlacedFrame, ...]


@dataclass
class Item:
    """A node or a pass-through slot in one layer."""

    key: object
    lane: int
    layer: int
    w: float
    h: float
    rank: int = 0
    cross: float = 0.0  # centre across layers
    ext: float = 0.0  # start along layers


def node_size(spec: NodeSpec) -> tuple[float, float, tuple[str, ...]]:
    lines = tuple(wrap_text(spec.label, WRAP)) or ("",)
    w = max(MIN_W, max(len(line) for line in lines) * CHAR_W + 2 * PAD_X)
    h = max(MIN_H, len(lines) * LINE_H + 2 * PAD_Y)
    if spec.shape == "diamond":
        w, h = w * 1.5, h * 1.6
    if spec.shape == "cylinder":
        h += 14
    return w, h, lines


def back_edges(ids: list[str], pairs: list[tuple[str, str]]) -> set[int]:
    """Indexes of edges that close a cycle in a DFS over `ids` in order."""
    out: dict[str, list[tuple[str, int]]] = {i: [] for i in ids}
    for index, (source, target) in enumerate(pairs):
        out[source].append((target, index))
    state: dict[str, int] = {}  # 1 on the stack, 2 finished
    found: set[int] = set()
    for root in ids:
        if root in state:
            continue
        state[root] = 1
        stack = [(root, iter(out[root]))]
        while stack:
            here, pending = stack[-1]
            step = next(pending, None)
            if step is None:
                state[here] = 2
                stack.pop()
                continue
            target, index = step
            if state.get(target) == 1:
                found.add(index)
            elif target not in state:
                state[target] = 1
                stack.append((target, iter(out[target])))
    return found


def assign_layers(ids: list[str], dag: list[tuple[str, str]]) -> dict[str, int]:
    """Longest-path layers of an acyclic edge list; the order of `ids` breaks ties."""
    incoming = dict.fromkeys(ids, 0)
    out: dict[str, list[str]] = {i: [] for i in ids}
    for source, target in dag:
        out[source].append(target)
        incoming[target] += 1
    layer = dict.fromkeys(ids, 0)
    ready = [i for i in ids if incoming[i] == 0]
    while ready:
        here = ready.pop(0)
        for target in out[here]:
            layer[target] = max(layer[target], layer[here] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    return layer


def _order_layers(
    items: dict[object, Item], links: list[tuple[object, object]]
) -> None:
    """Sweep layers down then up, sorting each lane's slots by neighbour averages."""
    above: dict[object, list[object]] = {k: [] for k in items}
    below: dict[object, list[object]] = {k: [] for k in items}
    for low, high in links:
        above[high].append(low)
        below[low].append(high)
    buckets: dict[tuple[int, int], list[Item]] = {}
    for item in items.values():
        buckets.setdefault((item.layer, item.lane), []).append(item)
    for members in buckets.values():
        for rank, item in enumerate(members):
            item.rank = rank
    top = max((layer for layer, _ in buckets), default=0)

    def pos(item: Item) -> float:
        return item.lane * 1000.0 + item.rank

    def sweep(layer: int, neighbours: dict[object, list[object]]) -> None:
        for (here, _), members in sorted(buckets.items()):
            if here != layer:
                continue

            def key(item: Item) -> tuple[float, float]:
                near = neighbours[item.key]
                if not near:
                    return pos(item), item.rank
                return sum(pos(items[n]) for n in near) / len(near), item.rank

            ordered = sorted(members, key=key)
            members[:] = ordered
            for rank, item in enumerate(ordered):
                item.rank = rank

    for _ in range(SWEEPS // 2):
        for layer in range(1, top + 1):
            sweep(layer, above)
        for layer in range(top - 1, -1, -1):
            sweep(layer, below)
    for members in buckets.values():
        members.sort(key=lambda item: item.rank)


def _label_box(label: str) -> tuple[tuple[str, ...], float, float]:
    lines = tuple(wrap_text(label, LABEL_WRAP))
    if not lines:
        return (), 0.0, 0.0
    return lines, max(len(x) for x in lines) * LABEL_CW + 8, len(lines) * LABEL_LH + 4


def loop_room(edges: list[EdgeSpec]) -> dict[object, float]:
    """Width a node reserves beside it for its self-loop and that loop's label."""
    room: dict[object, float] = {}
    for edge in edges:
        if edge.source != edge.target:
            continue
        label_w = _label_box(edge.label)[1]
        need = LOOP + 6 + (label_w + 4 if label_w else 0.0)
        room[edge.source] = max(room.get(edge.source, 0.0), need)
    return room


def _cross_size(item: Item, tb: bool) -> float:
    return item.w if tb else item.h


def _ext_size(item: Item, tb: bool) -> float:
    return item.h if tb else item.w


def _place_cross(
    items: dict[object, Item],
    lanes: int,
    tb: bool,
    lane_gap: float,
    loops: dict[object, float],
) -> None:
    """Centre coordinate across layers: lanes side by side, slots centred in a lane."""
    sizes = {
        k: _cross_size(i, tb) + (loops.get(k, 0.0) if tb else 0.0)
        for k, i in items.items()
    }
    rows: dict[tuple[int, int], list[Item]] = {}
    for item in items.values():
        rows.setdefault((item.lane, item.layer), []).append(item)
    width = [0.0] * lanes
    for (lane, _), row in rows.items():
        used = sum(sizes[i.key] for i in row) + NODE_GAP * (len(row) - 1)
        width[lane] = max(width[lane], used)
    start = 0.0
    for lane in range(lanes):
        for (here, _), row in sorted(rows.items()):
            if here != lane:
                continue
            row.sort(key=lambda item: item.rank)
            used = sum(sizes[i.key] for i in row) + NODE_GAP * (len(row) - 1)
            at = start + (width[lane] - used) / 2
            for item in row:
                item.cross = at + _cross_size(item, tb) / 2
                at += sizes[item.key] + NODE_GAP
        start += width[lane] + lane_gap


def _place_ext(
    items: dict[object, Item], tb: bool, gap: float
) -> tuple[list[float], list[float]]:
    """Band start and end per layer; each slot is centred in its band."""
    top = max(item.layer for item in items.values())
    band = [0.0] * (top + 1)
    for item in items.values():
        band[item.layer] = max(band[item.layer], _ext_size(item, tb))
    starts, ends, at = [], [], 0.0
    for layer in range(top + 1):
        starts.append(at)
        ends.append(at + band[layer])
        at += band[layer] + gap
    for item in items.values():
        item.ext = starts[item.layer] + (band[item.layer] - _ext_size(item, tb)) / 2
    return starts, ends


def _real(cross: float, ext: float, tb: bool) -> Point:
    return (cross, ext) if tb else (ext, cross)


def _dedupe(points: list[Point]) -> list[Point]:
    out: list[Point] = []
    for p in points:
        if not out or (abs(out[-1][0] - p[0]) > 1e-6 or abs(out[-1][1] - p[1]) > 1e-6):
            out.append(p)
    return out


def _route(
    chain: list[Item], bands: tuple[list[float], list[float]], tb: bool, shift: float
) -> tuple[list[Point], list[tuple[Point, Point]]]:
    """Points along a low-to-high chain, and its diagonal segments in the gaps."""
    starts, ends = bands
    pts: list[Point] = []
    gaps: list[tuple[Point, Point]] = []
    leaving: Point | None = None
    for n, item in enumerate(chain):
        c = item.cross + shift
        if n == 0:
            pts.append(_real(c, item.ext + _ext_size(item, tb), tb))
        else:
            entry = _real(c, starts[item.layer], tb)
            pts.append(entry)
            if leaving is not None:
                gaps.append((leaving, entry))
        if n == len(chain) - 1:
            pts.append(_real(c, item.ext, tb))
            continue
        leaving = _real(c, ends[item.layer], tb)
        pts.append(leaving)
    return pts, gaps


def _loop_points(box: Box) -> list[Point]:
    right = box.x + box.w
    top, bottom = box.y + box.h * 0.3, box.y + box.h * 0.7
    return [(right, top), (right + LOOP, top), (right + LOOP, bottom), (right, bottom)]


def _place_label(
    gap: tuple[Point, Point],
    size: tuple[float, float],
    taken: list[Box],
    solid: list[Box],
    tb: bool,
) -> Box:
    (x1, y1), (x2, y2) = gap
    w, h = size
    candidates = []
    for shift in (0.0, 1.0, -1.0, 2.0, -2.0):
        for t in (0.5, 0.4, 0.6):
            cx, cy = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
            if tb:
                cx += shift * (w / 2 + 4)
            else:
                cy += shift * (h / 2 + 4)
            box = Box(cx - w / 2, cy - h / 2, w, h)
            hits = sum(box.overlaps(o) for o in taken + solid)
            if hits == 0:
                return box
            candidates.append((hits, len(candidates), box))
    return min(candidates)[2]


def _translate(box: Box, dx: float, dy: float) -> Box:
    return Box(box.x + dx, box.y + dy, box.w, box.h)


Sizes = dict[str, tuple[float, float, tuple[str, ...]]]
Chains = list[tuple[int, list[object], bool]]


def _build_items(
    nodes: list[NodeSpec], edges: list[EdgeSpec], lane_names: list[str]
) -> tuple[dict[object, Item], Sizes, Chains, list[tuple[object, object]]]:
    """Slots for nodes and edge pass-throughs, plus each edge's slot chain."""
    ids = [n.id for n in nodes]
    real = [(i, e) for i, e in enumerate(edges) if e.source != e.target]
    pairs = [(e.source, e.target) for _, e in real]
    cut = back_edges(ids, pairs)
    forward = [(t, s) if n in cut else (s, t) for n, (s, t) in enumerate(pairs)]
    layer = assign_layers(ids, forward)
    items: dict[object, Item] = {}
    sizes: Sizes = {}
    for node in nodes:
        w, h, lines = node_size(node)
        sizes[node.id] = (w, h, lines)
        lane = lane_names.index(node.lane)
        items[node.id] = Item(node.id, lane, layer[node.id], w, h)
    chains: Chains = []
    links: list[tuple[object, object]] = []
    for n, (low, high) in enumerate(forward):
        keys: list[object] = [low]
        for at in range(layer[low] + 1, layer[high]):
            key = ("slot", n, at)
            items[key] = Item(key, items[low].lane, at, DUMMY, DUMMY)
            keys.append(key)
        keys.append(high)
        links += list(pairwise(keys))
        chains.append((real[n][0], keys, n in cut))
    return items, sizes, chains, links


def _place_nodes(
    nodes: list[NodeSpec], sizes: Sizes, items: dict[object, Item], tb: bool
) -> list[PlacedNode]:
    placed = []
    for node in nodes:
        w, h, lines = sizes[node.id]
        item = items[node.id]
        x, y = _real(item.cross, item.ext, tb)
        x, y = (x - w / 2, y) if tb else (x, y - h / 2)
        placed.append(PlacedNode(node, Box(x, y, w, h), lines))
    return placed


def _route_edges(
    edges: list[EdgeSpec],
    chains: Chains,
    items: dict[object, Item],
    bands: tuple[list[float], list[float]],
    tb: bool,
) -> dict[int, tuple[list[Point], tuple[Point, Point] | None]]:
    """Route every non-loop edge; parallel edges between a pair are offset."""
    total: dict[frozenset[str], int] = {}
    for index, _, _ in chains:
        k = frozenset((edges[index].source, edges[index].target))
        total[k] = total.get(k, 0) + 1
    seen: dict[frozenset[str], int] = {}
    routed: dict[int, tuple[list[Point], tuple[Point, Point] | None]] = {}
    for index, keys, reversed_ in chains:
        k = frozenset((edges[index].source, edges[index].target))
        nth = seen.get(k, 0)
        seen[k] = nth + 1
        shift = (nth - (total[k] - 1) / 2) * PARALLEL
        pts, gaps = _route([items[x] for x in keys], bands, tb, shift)
        pts = _dedupe(pts)
        routed[index] = (pts[::-1] if reversed_ else pts, gaps[0] if gaps else None)
    return routed


def _place_edges(
    edges: list[EdgeSpec],
    routed: dict[int, tuple[list[Point], tuple[Point, Point] | None]],
    boxes: dict[str, Box],
    tb: bool,
) -> list[PlacedEdge]:
    """Edge points, loops and labels; labels avoid nodes and each other."""
    solids = list(boxes.values())
    taken: list[Box] = []
    placed: list[PlacedEdge] = []
    for index, edge in enumerate(edges):
        lines, lw, lh = _label_box(edge.label)
        if edge.source == edge.target:
            loop = boxes[edge.source]
            pts = _loop_points(loop)
            at = (loop.x + loop.w + LOOP + 4 + lw / 2, loop.y + loop.h / 2)
            gap, vertical = (at, at), False
        else:
            pts, gap = routed[index]
            vertical = tb
        label_box = None
        if lines and gap is not None:
            label_box = _place_label(gap, (lw, lh), taken, solids, vertical)
            taken.append(label_box)
        placed.append(PlacedEdge(edge, tuple(pts), lines, label_box))
    return placed


def _place_frames(nodes: list[PlacedNode], frames: dict[str, str]) -> list[PlacedFrame]:
    placed = []
    for lane, label in frames.items():
        members = [p.box for p in nodes if p.spec.lane == lane]
        if not members:
            continue
        x0 = min(b.x for b in members) - FRAME_PAD
        y0 = min(b.y for b in members) - FRAME_PAD - FRAME_HEAD
        x1 = max(b.x + b.w for b in members) + FRAME_PAD
        y1 = max(b.y + b.h for b in members) + FRAME_PAD
        x1 = max(x1, x0 + len(label) * CHAR_W + 2 * FRAME_PAD + 28)
        placed.append(PlacedFrame(lane, label, Box(x0, y0, x1 - x0, y1 - y0)))
    return placed


def layout_graph(
    nodes: list[NodeSpec],
    edges: list[EdgeSpec],
    direction: str = "LR",
    frames: dict[str, str] | None = None,
) -> Layout:
    """Place nodes and route edges. `frames` maps a lane to the label of its frame."""
    frames = frames or {}
    tb = direction == "TB"
    lane_names = list(dict.fromkeys(n.lane for n in nodes))
    items, sizes, chains, links = _build_items(nodes, edges, lane_names)
    _order_layers(items, links)
    frame_room = 2 * FRAME_PAD + (0 if tb else FRAME_HEAD) if frames else 0
    loops = loop_room(edges)
    _place_cross(items, len(lane_names), tb, LANE_GAP + frame_room, loops)
    label_sizes = [_label_box(e.label) for e in edges]
    room = max((s[2] if tb else s[1] for s in label_sizes), default=0.0)
    bands = _place_ext(items, tb, LAYER_GAP + room)
    placed_nodes = _place_nodes(nodes, sizes, items, tb)
    boxes = {p.spec.id: p.box for p in placed_nodes}
    routed = _route_edges(edges, chains, items, bands, tb)
    placed_edges = _place_edges(edges, routed, boxes, tb)
    return _normalised(placed_nodes, placed_edges, _place_frames(placed_nodes, frames))


def _normalised(
    nodes: list[PlacedNode], edges: list[PlacedEdge], frames: list[PlacedFrame]
) -> Layout:
    """Shift everything so the drawing starts at the margin; add the viewBox size."""
    boxes = [n.box for n in nodes] + [f.box for f in frames]
    boxes += [e.label_box for e in edges if e.label_box is not None]
    xs = [p[0] for e in edges for p in e.points]
    ys = [p[1] for e in edges for p in e.points]
    left = min([b.x for b in boxes] + xs)
    top = min([b.y for b in boxes] + ys)
    right = max([b.x + b.w for b in boxes] + xs)
    bottom = max([b.y + b.h for b in boxes] + ys)
    dx, dy = MARGIN - left, MARGIN - top
    return Layout(
        right - left + 2 * MARGIN,
        bottom - top + 2 * MARGIN,
        tuple(PlacedNode(n.spec, _translate(n.box, dx, dy), n.lines) for n in nodes),
        tuple(
            PlacedEdge(
                e.spec,
                tuple((x + dx, y + dy) for x, y in e.points),
                e.label_lines,
                None if e.label_box is None else _translate(e.label_box, dx, dy),
            )
            for e in edges
        ),
        tuple(PlacedFrame(f.lane, f.label, _translate(f.box, dx, dy)) for f in frames),
    )
