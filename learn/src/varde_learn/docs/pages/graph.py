"""Task dependency graph: `deps` edges to fixed server-side inline SVG. Stdlib only."""

import html
from collections.abc import Mapping

_NODE_W, _NODE_H = 112, 30
_GAP_X, _GAP_Y, _PAD = 16, 40, 10
_MAX_LABEL = 16
_MAX_NODES = 200  # defined and unknown nodes together
_MAX_EDGES = 400


def parse_deps(edges: Mapping[str, object]) -> dict[str, list[str]]:
    """Map task id to its distinct dependency ids, from the `edges` prop."""
    graph: dict[str, list[str]] = {}
    for task, needs in edges.items():
        deps = graph.setdefault(task, [])
        for dep in needs if isinstance(needs, list) else []:
            if isinstance(dep, str) and dep and dep not in deps:
                deps.append(dep)
    return graph


def limit_graph(graph: dict[str, list[str]]) -> tuple[dict[str, list[str]], bool]:
    """Cap nodes and edges; also report whether anything was dropped."""
    kept: dict[str, list[str]] = {}
    nodes: set[str] = set()
    edges = 0
    truncated = False
    for task, deps in graph.items():
        if len(nodes) >= _MAX_NODES and task not in nodes:
            truncated = True
            continue
        nodes.add(task)
        kept[task] = []
        for dep in deps:
            full = dep not in nodes and len(nodes) >= _MAX_NODES
            if full or edges >= _MAX_EDGES:
                truncated = True
                continue
            nodes.add(dep)
            kept[task].append(dep)
            edges += 1
    return kept, truncated


def assign_layers(graph: dict[str, list[str]]) -> dict[str, int]:
    """Layer = longest dependency chain below a node; back edges of cycles are ignored.

    Unknown dependencies are layered too, as nodes with no dependencies.
    """
    layers: dict[str, int] = {}
    for root in [*graph, *(d for deps in graph.values() for d in deps)]:
        if root in layers:
            continue
        stack = [(root, iter(graph.get(root, [])))]
        active = {root}
        best = {root: 0}
        while stack:
            node, pending = stack[-1]
            nxt = next(pending, None)
            if nxt is None:
                layers[node] = best[node]
                active.discard(node)
                stack.pop()
                if stack:
                    parent = stack[-1][0]
                    best[parent] = max(best[parent], layers[node] + 1)
                continue
            if nxt in layers:
                best[node] = max(best[node], layers[nxt] + 1)
            elif nxt not in active:
                active.add(nxt)
                best[nxt] = 0
                stack.append((nxt, iter(graph.get(nxt, []))))
    return layers


def _label(name: str) -> str:
    return name if len(name) <= _MAX_LABEL else name[: _MAX_LABEL - 1] + "…"


def render_deps(edges: Mapping[str, object]) -> str:
    graph, truncated = limit_graph(parse_deps(edges))
    if not graph:
        return '<p class="graph-empty">No dependencies listed.</p>'
    layers = assign_layers(graph)
    rows: dict[int, list[str]] = {}
    for name, layer in layers.items():
        rows.setdefault(layer, []).append(name)
    widest = max(len(r) for r in rows.values())
    width = _PAD * 2 + widest * _NODE_W + (widest - 1) * _GAP_X
    height = _PAD * 2 + len(rows) * _NODE_H + (len(rows) - 1) * _GAP_Y
    pos: dict[str, tuple[float, float]] = {}
    for layer, names in rows.items():
        row_w = len(names) * _NODE_W + (len(names) - 1) * _GAP_X
        left = (width - row_w) / 2
        top = _PAD + layer * (_NODE_H + _GAP_Y)
        for n, name in enumerate(names):
            pos[name] = (left + n * (_NODE_W + _GAP_X), top)
    arrows = [
        _edge(pos[dep], pos[task], layers[dep] < layers[task])
        for task, deps in graph.items()
        for dep in deps
        if dep != task
    ]
    nodes = [_node(name, pos[name], name in graph) for name in layers]
    notice = (
        '<p class="graph-note">Graph truncated: too many tasks or dependencies.</p>'
        if truncated
        else ""
    )
    return (
        '<div class="scroll">'
        f'<svg class="dep-graph" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Task dependency graph" width="{width}" height="{height}" '
        f'preserveAspectRatio="xMidYMin meet" xmlns="http://www.w3.org/2000/svg">'
        '<defs><marker id="dep-arrow" viewBox="0 0 8 8" refX="7" refY="4" '
        'markerWidth="8" markerHeight="8" orient="auto">'
        '<path class="arrow" d="M0 0L8 4L0 8z"/></marker></defs>'
        + "".join(arrows)
        + "".join(nodes)
        + "</svg></div>"
        + notice
    )


def _edge(dep: tuple[float, float], task: tuple[float, float], forward: bool) -> str:
    """Arrow from the dependency to the task that needs it; sideways when same layer."""
    x1, y1 = dep[0] + _NODE_W / 2, dep[1] + _NODE_H
    x2, y2 = task[0] + _NODE_W / 2, task[1]
    cls = "edge"
    if not forward:  # same layer or a cycle back edge: curve from node sides
        cls = "edge back"
        x1, y1 = dep[0] + _NODE_W / 2, dep[1] + _NODE_H / 2
        x2, y2 = task[0] + _NODE_W / 2, task[1] + _NODE_H / 2
    mid = (y1 + y2) / 2
    return (
        f'<path class="{cls}" d="M{x1:.0f} {y1:.0f}C{x1:.0f} {mid:.0f} '
        f'{x2:.0f} {mid:.0f} {x2:.0f} {y2:.0f}" marker-end="url(#dep-arrow)"/>'
    )


def _node(name: str, at: tuple[float, float], known: bool) -> str:
    cls = "node" if known else "node missing"
    full = html.escape(name) + ("" if known else " (not defined)")
    return (
        f'<g class="{cls}"><title>{full}</title>'
        f'<rect x="{at[0]:.0f}" y="{at[1]:.0f}" width="{_NODE_W}" '
        f'height="{_NODE_H}" rx="4"/>'
        f'<text x="{at[0] + _NODE_W / 2:.0f}" y="{at[1] + _NODE_H / 2 + 4:.0f}" '
        f'text-anchor="middle">{html.escape(_label(name))}</text></g>'
    )
