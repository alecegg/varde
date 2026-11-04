"""Block type for structure: diagram (a graph or tree of nodes and edges)."""

from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    duplicates,
    str_field,
    tables,
    tables_fault,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec

KINDS = ("graph", "tree")
SHAPES = ("box", "rounded", "cylinder", "diamond")
EDGE_STYLES = ("solid", "dashed", "dotted")
DIRECTIONS = ("LR", "TB")
MAX_NODES = 200
MAX_EDGES = 400
MAX_GROUPS = 3  # one pre-computed layout per subset of collapsed groups


def _choice_fault(
    data: dict[str, object], key: str, allowed: tuple[str, ...], where: str
):
    if key in data and data[key] not in allowed:
        return [Fault("type", f"{where}: {key} must be one of {list(allowed)}")]
    return []


def _group_faults(data: dict[str, object]) -> tuple[list[Fault], list[str]]:
    faults = tables_fault(data, "groups", "diagram")
    entries = tables(data, "groups", "diagram")
    names = [n for g in entries if isinstance(n := g.get("id"), str)]
    faults += [
        Fault("group-duplicate", f"diagram: group id '{name}' is used more than once")
        for name in duplicates(names)
    ]
    if len(entries) > MAX_GROUPS:
        faults.append(Fault("too-many", f"diagram: at most {MAX_GROUPS} groups"))
    for n, group in enumerate(entries, 1):
        where = f"groups[{n}]"
        faults += check_keys(group, {"id", "label"}, set(), where)
        faults += str_field(group, "id", where) + str_field(group, "label", where)
    return faults, names


def _node_faults(
    data: dict[str, object], groups: list[str]
) -> tuple[list[Fault], list[str]]:
    faults = tables_fault(data, "nodes", "diagram")
    entries = tables(data, "nodes", "diagram")
    names = [n for e in entries if isinstance(n := e.get("id"), str)]
    faults += [
        Fault("node-duplicate", f"diagram: node id '{name}' is used more than once")
        for name in duplicates(names)
    ]
    if len(entries) > MAX_NODES:
        faults.append(Fault("too-many", f"diagram: at most {MAX_NODES} nodes"))
    for n, node in enumerate(entries, 1):
        where = f"nodes[{n}]"
        faults += check_keys(node, {"id", "label"}, {"group", "shape", "detail"}, where)
        for key in ("id", "label", "group", "detail"):
            faults += str_field(node, key, where)
        faults += _choice_fault(node, "shape", SHAPES, where)
        group = node.get("group")
        if isinstance(group, str) and group not in groups:
            faults.append(
                Fault("node-group", f"{where}: group '{group}' is not a group id")
            )
    return faults, names


def _edge_faults(data: dict[str, object], nodes: list[str]) -> list[Fault]:
    faults = tables_fault(data, "edges", "diagram")
    entries = tables(data, "edges", "diagram")
    if len(entries) > MAX_EDGES:
        faults.append(Fault("too-many", f"diagram: at most {MAX_EDGES} edges"))
    for n, edge in enumerate(entries, 1):
        where = f"edges[{n}]"
        faults += check_keys(edge, {"from", "to"}, {"label", "style"}, where)
        faults += _choice_fault(edge, "style", EDGE_STYLES, where)
        faults += str_field(edge, "label", where)
        for key in ("from", "to"):
            end = edge.get(key)
            if key in edge and not isinstance(end, str):
                faults.append(Fault("type", f"{where}.{key} must be a string"))
            elif isinstance(end, str) and end not in nodes:
                faults.append(
                    Fault("edge-target", f"{where}: {key} '{end}' is not a node id")
                )
    return faults


def _tree_faults(data: dict[str, object]) -> list[Fault]:
    """A tree has one parent per node and no cycle."""
    parent: dict[str, str] = {}
    faults: list[Fault] = []
    for edge in tables(data, "edges", "diagram"):
        source, target = edge.get("from"), edge.get("to")
        if not (isinstance(source, str) and isinstance(target, str)):
            continue
        if target in parent:
            faults.append(
                Fault("tree-parent", f"diagram: tree node '{target}' has two parents")
            )
        parent[target] = source
    for start in parent:
        seen, here = {start}, parent.get(start)
        while here is not None and here not in seen:
            seen.add(here)
            here = parent.get(here)
        if here is not None:
            faults.append(
                Fault("tree-cycle", f"diagram: tree has a cycle through '{start}'")
            )
            break
    return faults


def validate_diagram(data: dict[str, object]) -> list[Fault]:
    required, optional = (
        {"kind", "nodes"},
        {"edges", "direction", "groups", "title", "desc"},
    )
    faults = check_keys(data, required, optional, "diagram")
    faults += str_field(data, "title", "diagram") + str_field(data, "desc", "diagram")
    faults += _choice_fault(data, "kind", KINDS, "diagram")
    faults += _choice_fault(data, "direction", DIRECTIONS, "diagram")
    group_faults, groups = _group_faults(data)
    node_faults, nodes = _node_faults(data, groups)
    faults += group_faults + node_faults + _edge_faults(data, nodes)
    used = {
        g
        for n in tables(data, "nodes", "diagram")
        if isinstance(g := n.get("group"), str)
    }
    faults += [
        Fault("group-empty", f"diagram: group '{g}' has no nodes")
        for g in groups
        if g not in used
    ]
    if data.get("kind") == "tree":
        faults += _tree_faults(data)
    return faults


DIAGRAM = BlockSpec(
    "diagram",
    "A graph or tree of nodes and edges, laid out and drawn as SVG",
    (
        "kind        graph or tree",
        "nodes: list of {id, label, group, shape, detail}",
        "  id      unique node name",
        "  label   text on the node",
        "  group   optional group id; the group can be collapsed",
        "  shape   optional: box (default), rounded, cylinder or diamond",
        "  detail  optional longer text shown when the node is selected",
        "edges: optional list of {from, to, label, style}",
        "  from, to  node ids",
        "  label     optional text on the edge",
        "  style     optional: solid (default), dashed or dotted",
        "groups: optional list of {id, label}, at most 3",
        "direction   optional LR (graph default) or TB (tree default)",
        "title, desc optional text",
        f"limits: {MAX_NODES} nodes, {MAX_EDGES} edges; a tree has one parent per node",
    ),
    r"""diagram = diagram(
  kind: "graph",
  title: "Request path",
  direction: "LR",
  groups: [{"id": "edge", "label": "Edge"}, {"id": "core", "label": "Core"}],
  nodes: [
    {"id": "user", "label": "User", "shape": "rounded"},
    {"id": "gw", "label": "Gateway", "group": "edge", "detail": "Terminates TLS"},
    {"id": "api", "label": "API", "group": "core"},
    {"id": "db", "label": "Database", "group": "core", "shape": "cylinder"},
  ],
  edges: [
    {"from": "user", "to": "gw", "label": "https"},
    {"from": "gw", "to": "api"},
    {"from": "api", "to": "db", "label": "sql", "style": "dashed"},
  ],
)
""",
    validate_diagram,
)
