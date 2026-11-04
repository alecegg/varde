"""HTML for the flow block: a top-down diagram of step cards laid out on the server.

A flow is a graph preset: each step is a node labelled with its text and each
`next` entry is an edge, laid out by the diagram layered layout. The ordered list
of steps stays in the page as the text alternative; `static/flow.js` only adds
the dependency highlight and pan and zoom.
"""

from varde_learn.docs.pages.blocks_render.common import (
    as_dict,
    as_list,
    badge,
    card,
    esc,
)
from varde_learn.docs.pages.blocks_render.diagram_layout import (
    MIN_H,
    EdgeSpec,
    NodeSpec,
    layout_graph,
)
from varde_learn.docs.pages.blocks_render.diagrams import _state
from varde_learn.docs.pages.blocks_render.svg import copy_attr


def _steps(data: dict[str, object]) -> list[dict[str, object]]:
    """Steps in document order; a repeated id keeps its first step."""
    seen: dict[str, dict[str, object]] = {}
    for step in map(as_dict, as_list(data.get("step"))):
        seen.setdefault(str(step["id"]), step)
    return list(seen.values())


def _targets(step: dict[str, object], known: set[str]) -> list[str]:
    return [str(t) for t in as_list(step.get("next")) if str(t) in known]


def _specs(
    steps: list[dict[str, object]],
) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    known = {str(s["id"]) for s in steps}
    nodes = [
        NodeSpec(
            str(s["id"]),
            str(s["text"]),
            "box" if _targets(s, known) else "rounded",
        )
        for s in steps
    ]
    edges = [
        EdgeSpec(str(s["id"]), target)
        for s in steps
        for target in dict.fromkeys(_targets(s, known))
    ]
    return nodes, edges


def _summary(data: dict[str, object]) -> str:
    count = len(_steps(data))
    return f"flow of {count} step{'' if count == 1 else 's'}"


def copy_text(data: dict[str, object]) -> str:
    """Plain text for the Copy entry: the steps in order, each with what follows."""
    steps = _steps(data)
    known = {str(s["id"]) for s in steps}
    lines = [f"{data.get('title', 'Flow')} ({_summary(data)})"]
    for n, step in enumerate(steps, 1):
        line = f"{n}. {step['id']}: {step['text']}"
        targets = _targets(step, known)
        if targets:
            line += f" -> {', '.join(targets)}"
        lines.append(line)
    return "\n".join(lines)


def _step(step: dict[str, object], known: set[str]) -> str:
    targets = _targets(step, known)
    nxt = ""
    if targets:
        names = ", ".join(f"<code>{esc(t)}</code>" for t in targets)
        branch = badge("branch", "vb-branch") + " " if len(targets) > 1 else ""
        nxt = f'<div class="vb-next">{branch}then {names}</div>'
    return (
        f'<li class="vb-step" data-node="{esc(step["id"])}">'
        f'<code class="vb-step-id">{esc(step["id"])}</code> '
        f'<span class="vd-detail-text">{esc(step["text"])}</span>{nxt}</li>'
    )


def _alternative(data: dict[str, object]) -> str:
    steps = _steps(data)
    known = {str(s["id"]) for s in steps}
    items = "".join(_step(s, known) for s in steps)
    return (
        '<details class="vb-data"><summary>Steps as text</summary>'
        f'<p class="vb-alt">{esc(_summary(data))}</p>'
        f'<ol class="vb-flow">{items}</ol></details>'
    )


def _view(data: dict[str, object]) -> str:
    nodes, edges = _specs(_steps(data))
    props = {
        "kind": "flow",
        "title": data.get("title", "Flow"),
        "desc": f"{_summary(data)}, top to bottom",
        "nodes": [],
    }
    return _state(0, layout_graph(nodes, edges, "TB"), props, [], {})


def render_flow(data: dict[str, object]) -> str:
    heading = esc(data["title"]) if "title" in data else ""
    if not _steps(data):
        return '<div class="vb">' + card(heading, _alternative(data)) + "</div>"
    unit = f'data-min-unit="{MIN_H:g}"'
    body = f'<div class="vd-views" {unit}>{_view(data)}</div>{_alternative(data)}'
    return (
        f'<div class="vb flow"{copy_attr(copy_text(data))}>{card(heading, body)}</div>'
    )
