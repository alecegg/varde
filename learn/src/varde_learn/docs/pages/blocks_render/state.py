"""HTML and SVG for the state block, drawn on the flow layout.

`state_graph` adapts the states and transitions to `layout_graph`; this module draws
the result: start dot, double border for final, cross mark for error, dashed border
for unreachable, self-loops with their label beside the node. The drawing
sits at 1:1 scale in a scroll region and needs no script. Below it the states and an
ordered list of transitions are the text alternative, the print form and the copy
text. Colours come only from `--vd-*` tokens in `60-state.css`.
"""

from dataclasses import replace

from varde_learn.docs.pages.blocks_render.common import count_noun, esc
from varde_learn.docs.pages.blocks_render.diagram_layout import (
    Box,
    PlacedEdge,
    PlacedNode,
    layout_graph,
)
from varde_learn.docs.pages.blocks_render.diagrams import _head, _text
from varde_learn.docs.pages.blocks_render.state_graph import (
    KIND_WORDS,
    Props,
    free_id,
    kind_of,
    loop_labels,
    states_of,
    transition_text,
    transitions_of,
    unreachable_ids,
)
from varde_learn.docs.pages.blocks_render.state_graph import (
    graph_specs as specs,
)
from varde_learn.docs.pages.blocks_render.svg import copy_attr, svg_root

DOT_R = 8.0
RING = 4.0
LINE = 16.0


Names = dict[str, tuple[str, str]]


def _dot(box: Box) -> str:
    circle = (
        f'<circle class="vd-state-dot" cx="{box.w / 2:.1f}" '
        f'cy="{box.h / 2:.1f}" r="{DOT_R:g}"/>'
    )
    pos = f'transform="translate({box.x:.1f} {box.y:.1f})"'
    title = "<title>initial state marker</title>"
    return f'<g class="vd-state-start" {pos}>{title}{circle}</g>'


def _node(node: PlacedNode, names: Names, dim: set[str], start: str) -> str:
    spec, box = node.spec, node.box
    pos = f'transform="translate({box.x:.1f} {box.y:.1f})"'
    if spec.id == start:
        return _dot(box)
    kind, unreachable = names[spec.id][1], spec.id in dim
    cls = f"vd-state-node vd-state-{kind}" + (
        " vd-state-unreachable" if unreachable else ""
    )
    shape = (
        f'<rect class="vd-state-shape" width="{box.w:.1f}" '
        f'height="{box.h:.1f}" rx="10"/>'
    )
    if kind == "final":
        ring = (
            f'<rect class="vd-state-ring" x="{RING:g}" y="{RING:g}" '
            f'width="{box.w - 2 * RING:.1f}" height="{box.h - 2 * RING:.1f}" rx="7"/>'
        )
        shape += ring
    said = f"{names[spec.id][0]}, {KIND_WORDS[kind]}" + (
        ", unreachable" if unreachable else ""
    )
    text = _text(node.lines, "vd-state-label", box.w / 2, box.h / 2, LINE)
    return f'<g class="{cls}" {pos}><title>{esc(said)}</title>{shape}{text}</g>'


def _label(box: Box, lines: tuple[str, ...]) -> str:
    return (
        f'<rect class="vd-state-label-bg" x="{box.x:.1f}" y="{box.y:.1f}" '
        f'width="{box.w:.1f}" height="{box.h:.1f}" rx="3"/>'
        + _text(
            lines, "vd-state-edge-label", box.x + box.w / 2, box.y + box.h / 2, 14.0
        )
    )


def _edge(edge: PlacedEdge, said: str) -> str:
    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in edge.points)
    head = _head(edge.points).replace("vd-head", "vd-state-head")
    box, lines = edge.label_box, edge.label_lines
    label = _label(box, lines) if box is not None and lines else ""
    return (
        f'<g class="vd-state-edge"><title>{esc(said)}</title>'
        f'<path class="vd-state-line" d="{d}"/>{head}{label}</g>'
    )


def _start_edge(edge: PlacedEdge, marker: Box) -> PlacedEdge:
    """The arrow leaves the dot, not the empty layout box around it."""
    x = edge.points[0][0]
    leaving = (x, marker.y + marker.h / 2 + DOT_R)
    return replace(edge, points=(leaving, *edge.points[1:]))


def _edge_texts(
    moves: list[Props], labels: dict[str, str], first: str | None
) -> list[str]:
    """Spoken text per layout edge, in the order `graph_specs` emits them."""
    plain = [m for m in moves if m["from"] != m["to"]]
    texts = [] if first is None else [f"initial state marker to {labels[first]}"]
    texts += [transition_text(m, labels) for m in plain]
    for state in loop_labels(moves):
        own = [m for m in moves if m["from"] == m["to"] == state]
        texts.append(" / ".join(transition_text(m, labels) for m in own))
    return texts


def _drawing(data: Props, name: str, desc: str) -> str:
    states = states_of(data)
    ids = {str(s["id"]) for s in states}
    moves = transitions_of(data, ids)
    start = free_id(ids)
    nodes, edges = specs(states, moves, start)
    layout = layout_graph(nodes, edges, "TB")
    names = {str(s["id"]): (str(s["label"]), kind_of(s)) for s in states}
    initial = next((str(s["id"]) for s in states if kind_of(s) == "initial"), None)
    said = _edge_texts(moves, {i: v[0] for i, v in names.items()}, initial)
    marker = next((n.box for n in layout.nodes if n.spec.id == start), None)
    body = ""
    for index, placed in enumerate(layout.edges):
        from_marker = marker is not None and placed.spec.source == start
        edge = _start_edge(placed, marker) if from_marker and marker else placed
        body += _edge(edge, said[index])
    dim = unreachable_ids(states, moves)
    body += "".join(_node(n, names, dim, start) for n in layout.nodes)
    right, bottom = layout.width, layout.height
    svg = svg_root(name, desc, (0.0, 0.0, right, bottom), body, "vd-state-svg")
    return svg.replace("<svg ", f'<svg width="{right:g}" height="{bottom:g}" ', 1)


def _state_item(state: Props, dim: set[str]) -> str:
    words = KIND_WORDS[kind_of(state)] + (
        ", unreachable from the initial state" if str(state["id"]) in dim else ""
    )
    note = f": {state['note']}" if "note" in state else ""
    return f'<li class="vd-state-item">{esc(state["label"])} ({words}){esc(note)}</li>'


def _summary(states: list[Props], moves: list[Props]) -> str:
    return f"{count_noun(len(states), 'state', 'states')}, " + count_noun(
        len(moves), "transition", "transitions"
    )


def copy_text(
    title: str, states: list[Props], moves: list[Props], texts: list[str]
) -> str:
    lines = [f"{title} ({_summary(states, moves)})", "States:"]
    lines += [f"- {s['label']} ({KIND_WORDS[kind_of(s)]})" for s in states]
    if texts:
        lines.append("Transitions:")
        lines += [f"{n}. {t}" for n, t in enumerate(texts, 1)]
    return "\n".join(lines)


def render_state(data: dict[str, object]) -> str:
    states = states_of(data)
    moves = transitions_of(data, {str(s["id"]) for s in states})
    labels = {str(s["id"]): str(s["label"]) for s in states}
    texts = [transition_text(m, labels) for m in moves]
    dim = unreachable_ids(states, moves)
    counts = _summary(states, moves)
    title, desc = str(data.get("title", "")), str(data["desc"])
    name = title or "State machine"
    head = f'<h4 class="vb-title vd-state-title">{esc(title)}</h4>' if title else ""
    region = f'role="region" tabindex="0" aria-label="{esc(name)} (scrollable)"'
    view = f'<div class="vd-state-view" {region}>{_drawing(data, name, desc)}</div>'
    items = "".join(_state_item(s, dim) for s in states)
    steps = "".join(f'<li class="vd-state-item">{esc(t)}</li>' for t in texts)
    ordered = (
        f'<ol class="vd-state-moves" aria-label="Transitions">{steps}</ol>'
        if texts
        else ""
    )
    copy = copy_attr(copy_text(name, states, moves, texts))
    summary = f'<p class="vb-alt vd-state-summary">{esc(desc)} ({counts})</p>'
    listing = f'<ul class="vd-state-states" aria-label="States">{items}</ul>'
    root = f'<div class="vb state vd-state"{copy}>'
    return f"{root}{head}{summary}{view}{listing}{ordered}</div>"
