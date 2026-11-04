"""Graph and tree diagrams as server-laid-out SVG, one layout per collapse state.

`diagram_states` lays out every subset of collapsed groups (at most 3 groups,
so at most 8 layouts); the page script only shows one and toggles `hidden`.
The first state (nothing collapsed) is what a static export shows.
"""

import math

from varde_learn.docs.pages.blocks_render.common import as_dict, as_list, card, esc
from varde_learn.docs.pages.blocks_render.diagram_layout import (
    FRAME_HEAD,
    MIN_H,
    Box,
    EdgeSpec,
    Layout,
    NodeSpec,
    PlacedEdge,
    PlacedFrame,
    PlacedNode,
    layout_graph,
)
from varde_learn.docs.pages.blocks_render.svg import copy_attr, svg_root

HEAD_LEN, HEAD_HALF = 10.0, 5.0
GROUP_CLASSES = 3


def _graph(props: dict[str, object]):
    groups = [
        (str(g["id"]), str(g["label"]))
        for g in map(as_dict, as_list(props.get("groups")))
    ]
    nodes = [
        NodeSpec(
            str(n["id"]),
            str(n["label"]),
            str(n.get("shape", "box")),
            str(n.get("group", "")),
        )
        for n in map(as_dict, as_list(props["nodes"]))
    ]
    edges = [
        EdgeSpec(
            str(e["from"]),
            str(e["to"]),
            str(e.get("label", "")),
            str(e.get("style", "solid")),
        )
        for e in map(as_dict, as_list(props.get("edges")))
    ]
    return groups, nodes, edges


def direction_of(props: dict[str, object]) -> str:
    return str(props.get("direction") or ("TB" if props["kind"] == "tree" else "LR"))


def collapse(
    nodes: list[NodeSpec], edges: list[EdgeSpec], labels: dict[str, str], shut: set[str]
) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    """The graph with each group in `shut` replaced by one node `group:<id>`."""
    taken = {n.id for n in nodes}
    name = {g: _free(f"group:{g}", taken) for g in shut}
    count = {g: sum(1 for n in nodes if n.lane == g) for g in shut}
    out: list[NodeSpec] = []
    for node in nodes:
        if node.lane not in shut:
            out.append(node)
        elif not any(o.id == name[node.lane] for o in out):
            label = f"{labels[node.lane]} ({count[node.lane]})"
            out.append(NodeSpec(name[node.lane], label, "super", node.lane))
    where = {n.id: name[n.lane] for n in nodes if n.lane in shut}
    seen: dict[tuple[str, str], EdgeSpec] = {}
    for edge in edges:
        source, target = (
            where.get(edge.source, edge.source),
            where.get(edge.target, edge.target),
        )
        internal = source == target and edge.source != edge.target
        if internal or (source, target) in seen:
            continue
        seen[(source, target)] = EdgeSpec(source, target, edge.label, edge.style)
    return out, list(seen.values())


def _free(name: str, taken: set[str]) -> str:
    while name in taken:
        name += "#"
    return name


def diagram_states(props: dict[str, object]) -> list[tuple[int, Layout]]:
    """(collapsed-group bit mask, layout) for every subset; mask 0 comes first."""
    groups, nodes, edges = _graph(props)
    labels = dict(groups)
    direction = direction_of(props)
    states = []
    for mask in range(2 ** len(groups)):
        shut = {g for bit, (g, _) in enumerate(groups) if mask >> bit & 1}
        shown_nodes, shown_edges = (
            collapse(nodes, edges, labels, shut) if shut else (nodes, edges)
        )
        frames = {g: label for g, label in groups if g not in shut}
        states.append((mask, layout_graph(shown_nodes, shown_edges, direction, frames)))
    return states


def _lane_class(lane: str, groups: list[str]) -> str:
    if lane not in groups:
        return ""
    return f" vd-g{groups.index(lane) % GROUP_CLASSES + 1}"


def _shape(shape: str, box: Box) -> str:
    w, h = box.w, box.h
    if shape == "diamond":
        pts = f"{w / 2:.1f},0 {w:.1f},{h / 2:.1f} {w / 2:.1f},{h:.1f} 0,{h / 2:.1f}"
        return f'<polygon class="vd-shape" points="{pts}"/>'
    if shape == "cylinder":
        ry = 7.0
        body = (
            f"M0 {ry} V{h - ry:.1f} A{w / 2:.1f} {ry} 0 0 0 {w:.1f} {h - ry:.1f} "
            f"V{ry} A{w / 2:.1f} {ry} 0 0 1 0 {ry}Z"
        )
        top = (
            f'<ellipse class="vd-shape vd-cap" cx="{w / 2:.1f}" cy="{ry}" '
            f'rx="{w / 2:.1f}" ry="{ry}"/>'
        )
        return f'<path class="vd-shape" d="{body}"/>{top}'
    radius = min(h / 2, 18) if shape == "rounded" else 3
    return (
        f'<rect class="vd-shape" width="{w:.1f}" height="{h:.1f}" rx="{radius:.1f}"/>'
    )


def _text(lines: tuple[str, ...], cls: str, x: float, y: float, line_h: float) -> str:
    top = y - (len(lines) - 1) * line_h / 2
    spans = "".join(
        f'<tspan x="{x:.1f}" y="{top + n * line_h:.1f}">{esc(line)}</tspan>'
        for n, line in enumerate(lines)
    )
    anchor = 'text-anchor="middle" dominant-baseline="central"'
    return f'<text class="{cls}" {anchor}>{spans}</text>'


def _node(node: PlacedNode, groups: list[str], bits: dict[str, int]) -> str:
    spec, box = node.spec, node.box
    pos = f'transform="translate({box.x:.1f} {box.y:.1f})"'
    shut = spec.shape == "super"
    cls = f"vd-node vd-{spec.shape}{_lane_class(spec.lane, groups)}"
    extra = f' data-bit="{bits[spec.lane]}"' if shut else ""
    body = _shape(spec.shape, box) + _text(
        node.lines, "vd-label", box.w / 2, box.h / 2, 16.0
    )
    return (
        f'<g class="{cls}" data-id="{esc(spec.id)}"{extra} {pos}>'
        f"<title>{esc(spec.label)}</title>{body}</g>"
    )


def _head(points: tuple[tuple[float, float], ...]) -> str:
    (x1, y1), (x2, y2) = points[-2], points[-1]
    length = math.hypot(x2 - x1, y2 - y1) or 1.0
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    bx, by = x2 - ux * HEAD_LEN, y2 - uy * HEAD_LEN
    left = (bx - uy * HEAD_HALF, by + ux * HEAD_HALF)
    right = (bx + uy * HEAD_HALF, by - ux * HEAD_HALF)
    pts = f"{x2:.1f},{y2:.1f} {left[0]:.1f},{left[1]:.1f} {right[0]:.1f},{right[1]:.1f}"
    return f'<polygon class="vd-head" points="{pts}"/>'


def _edge(edge: PlacedEdge, names: dict[str, str]) -> str:
    spec = edge.spec
    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in edge.points)
    label = ""
    if edge.label_box is not None:
        b = edge.label_box
        label = (
            f'<rect class="vd-elabel-bg" x="{b.x:.1f}" y="{b.y:.1f}" width="{b.w:.1f}" '
            f'height="{b.h:.1f}" rx="3"/>'
            + _text(edge.label_lines, "vd-elabel", b.x + b.w / 2, b.y + b.h / 2, 14.0)
        )
    source = names.get(spec.source, spec.source)
    said = f"{source} to {names.get(spec.target, spec.target)}"
    said += f": {spec.label}" if spec.label else ""
    return (
        f'<g class="vd-edge vd-{spec.style}" data-from="{esc(spec.source)}" '
        f'data-to="{esc(spec.target)}"><title>{esc(said)}</title>'
        f'<path class="vd-line" d="{d}"/>{_head(edge.points)}{label}</g>'
    )


def _frame(frame: PlacedFrame, groups: list[str], bits: dict[str, int]) -> str:
    b = frame.box
    cls = f"vd-group{_lane_class(frame.lane, groups)}"
    mid = b.y + FRAME_HEAD / 2
    head = (
        f'<g class="vd-group-head" data-bit="{bits[frame.lane]}" '
        f'data-group="{esc(frame.lane)}">'
        f'<rect class="vd-head-hit" x="{b.x:.1f}" y="{b.y:.1f}" width="{b.w:.1f}" '
        f'height="{FRAME_HEAD:g}" rx="8"/>'
        f'<text class="vd-chev" x="{b.x + 12:.1f}" y="{mid:.1f}" '
        f'dominant-baseline="central">\u25be</text>'
        f'<text class="vd-group-label" x="{b.x + 30:.1f}" y="{mid:.1f}" '
        f'dominant-baseline="central">{esc(frame.label)}</text></g>'
    )
    rect = (
        f'<rect class="vd-frame" x="{b.x:.1f}" y="{b.y:.1f}" width="{b.w:.1f}" '
        f'height="{b.h:.1f}" rx="8"/>'
    )
    return f'<g class="{cls}">{rect}{head}</g>'


def _state(
    mask: int,
    layout: Layout,
    props: dict[str, object],
    groups: list[str],
    bits: dict[str, int],
) -> str:
    names = {n.spec.id: n.spec.label for n in layout.nodes}
    inner = (
        "".join(_frame(f, groups, bits) for f in layout.frames)
        + "".join(_edge(e, names) for e in layout.edges)
        + "".join(_node(n, groups, bits) for n in layout.nodes)
    )
    title = str(props.get("title", "Diagram"))
    desc = str(props.get("desc", "")) or text_summary(props)
    box = (0.0, 0.0, layout.width, layout.height)
    natural = f'width="{layout.width:g}" height="{layout.height:g}" '
    svg = svg_root(title, desc, box, inner, "vd-svg").replace(
        "<svg ", "<svg " + natural, 1
    )
    hidden = " hidden" if mask else ""
    name = f'role="region" tabindex="0" aria-label="{esc(title)} (scrollable)"'
    return f'<div class="vd-view" data-mask="{mask}" {name}{hidden}>{svg}</div>'


def text_summary(props: dict[str, object]) -> str:
    n, e = len(as_list(props["nodes"])), len(as_list(props.get("edges")))
    return f"{props['kind']} with {n} nodes and {e} edges"


def copy_text(props: dict[str, object]) -> str:
    """Plain text for the Copy entry: title, nodes, then edges, by label."""
    _, nodes, edges = _graph(props)
    label = {n.id: n.label for n in nodes}
    lines = [f"{props.get('title', 'Diagram')} ({text_summary(props)})", "Nodes:"]
    lines += [f"- {n.label} [{n.shape}]" for n in nodes]
    lines.append("Edges:")
    for e in edges:
        said = f"- {label[e.source]} -> {label[e.target]}"
        lines.append(said + (f": {e.label}" if e.label else ""))
    return "\n".join(lines)


def _alternative(props: dict[str, object]) -> str:
    groups, nodes, edges = _graph(props)
    group_name = dict(groups)
    details = {
        str(n["id"]): n.get("detail") for n in map(as_dict, as_list(props["nodes"]))
    }
    label = {n.id: n.label for n in nodes}
    items = []
    for n in nodes:
        tags = [n.shape] + ([f"group {group_name[n.lane]}"] if n.lane else [])
        note = details.get(n.id)
        more = f': <span class="vd-detail-text">{esc(note)}</span>' if note else ""
        items.append(
            f'<li data-node="{esc(n.id)}"><strong>{esc(n.label)}</strong> '
            f"({esc(', '.join(tags))}){more}</li>"
        )
    links = "".join(
        f'<li data-from="{esc(e.source)}" data-to="{esc(e.target)}">'
        f"{esc(label[e.source])} to "
        f"{esc(label[e.target])}"
        + (f": {esc(e.label)}" if e.label else "")
        + (f" ({esc(e.style)})" if e.style != "solid" else "")
        + "</li>"
        for e in edges
    )
    edge_block = f"<h5>Edges</h5><ul>{links}</ul>" if links else ""
    return (
        '<details class="vb-data"><summary>Nodes and edges as text</summary>'
        f'<p class="vb-alt">{esc(text_summary(props))}</p>'
        f"<h5>Nodes</h5><ul>{''.join(items)}</ul>{edge_block}</details>"
    )


def render_diagram(props: dict[str, object]) -> str:
    groups, _, _ = _graph(props)
    ids = [g for g, _ in groups]
    bits = {g: 1 << n for n, g in enumerate(ids)}
    states = "".join(
        _state(m, lay, props, ids, bits) for m, lay in diagram_states(props)
    )
    heading = esc(props["title"]) if "title" in props else ""
    unit = f'data-min-unit="{min(MIN_H, FRAME_HEAD):g}"'
    body = f'<div class="vd-views" {unit}>{states}</div>{_alternative(props)}'
    root = f'<div class="vb diagram"{copy_attr(copy_text(props))}>'
    return f"{root}{card(heading, body)}</div>"
