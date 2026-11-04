"""Pure adapter from a `state` block to the flow layout: nodes, edges, texts.

No I/O and no HTML. A state becomes a layout node and a transition a labelled
edge. What the layout lacks is added here: a synthetic start node for the initial
marker, one merged self-loop per state with its label, and the reachability and
text-alternative helpers.
"""

from collections.abc import Mapping, Sequence

from varde_learn.docs.pages.blocks_render.common import as_dict, as_list
from varde_learn.docs.pages.blocks_render.diagram_layout import (
    EdgeSpec,
    NodeSpec,
)

Props = Mapping[str, object]
KIND_WORDS = {
    "initial": "initial state",
    "normal": "state",
    "final": "final state",
    "error": "error state",
}
NODE_CLIP = 60
LABEL_CLIP = 40
ERROR_GLYPH = "✕ "


def clip(text: str, limit: int) -> str:
    """The text cut to `limit` characters, a cut marked with an ellipsis."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def states_of(data: Props) -> list[Props]:
    """States in document order; a repeated id keeps its first state."""
    seen: dict[str, Props] = {}
    for state in map(as_dict, as_list(data.get("states"))):
        seen.setdefault(str(state["id"]), state)
    return list(seen.values())


def transitions_of(data: Props, ids: set[str]) -> list[Props]:
    """Transitions whose two ends are known states, in document order."""
    moves = map(as_dict, as_list(data.get("transitions")))
    return [t for t in moves if str(t["from"]) in ids and str(t["to"]) in ids]


def kind_of(state: Props) -> str:
    return str(state.get("kind", "normal"))


def edge_label(move: Props) -> str:
    """`start [guard]`, `start`, `[guard]` or an empty string."""
    parts = [str(move["label"])] if "label" in move else []
    if "guard" in move:
        parts.append(f"[{move['guard']}]")
    return " ".join(parts)


def transition_text(move: Props, labels: Mapping[str, str]) -> str:
    """`Idle to Running on start [guard]`."""
    said = f"{labels[str(move['from'])]} to {labels[str(move['to'])]}"
    if "label" in move:
        said += f" on {move['label']}"
    if "guard" in move:
        said += f" [{move['guard']}]"
    return said


def unreachable_ids(states: Sequence[Props], moves: Sequence[Props]) -> set[str]:
    """States no path from an initial state reaches; empty without an initial state."""
    out: dict[str, list[str]] = {str(s["id"]): [] for s in states}
    for move in moves:
        out[str(move["from"])].append(str(move["to"]))
    seen = {str(s["id"]) for s in states if kind_of(s) == "initial"}
    queue = list(seen)
    while queue:
        for target in out[queue.pop(0)]:
            if target not in seen:
                seen.add(target)
                queue.append(target)
    if not seen:
        return set()
    return set(out) - seen


def node_label(state: Props) -> str:
    glyph = ERROR_GLYPH if kind_of(state) == "error" else ""
    return glyph + clip(str(state["label"]), NODE_CLIP)


def free_id(taken: set[str]) -> str:
    """An id for the start marker that no state uses."""
    name = "·start"
    while name in taken:
        name += "#"
    return name


def loop_labels(moves: Sequence[Props]) -> dict[str, str]:
    """One merged label per state that has self-transitions, in document order."""
    merged: dict[str, list[str]] = {}
    for move in moves:
        if move["from"] == move["to"]:
            merged.setdefault(str(move["from"]), []).append(edge_label(move))
    return {k: clip("; ".join(v), LABEL_CLIP) for k, v in merged.items()}


def graph_specs(
    states: Sequence[Props], moves: Sequence[Props], start: str
) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    """Layout input: the start marker node first, one edge per pair of ends.

    A state with several self-transitions gets one loop carrying the merged label;
    the layout reserves room beside the node for it.
    """
    first = next((s for s in states if kind_of(s) == "initial"), None)
    nodes = [NodeSpec(str(s["id"]), node_label(s)) for s in states]
    edges = [
        EdgeSpec(str(m["from"]), str(m["to"]), clip(edge_label(m), LABEL_CLIP))
        for m in moves
        if m["from"] != m["to"]
    ]
    loops = [EdgeSpec(k, k, v) for k, v in loop_labels(moves).items()]
    if first is None:
        return nodes, edges + loops
    marker = NodeSpec(start, "")
    return [marker, *nodes], [EdgeSpec(start, str(first["id"])), *edges, *loops]
