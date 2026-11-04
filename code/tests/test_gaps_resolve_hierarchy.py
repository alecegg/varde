from typing import Any, cast

from varde_code.index.resolve import resolve


def resolve_graph(*args: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", resolve(*args))


def test_resolves_extends_and_implements_to_unique_type_entities():
    entities = [
        {"kind": "class", "name": "Child", "file_id": 0},
        {
            "kind": "extends",
            "name": "Base",
            "file_id": 0,
            "enclosing_function": "Child",
        },
        {
            "kind": "implements",
            "name": "Renderable",
            "file_id": 0,
            "enclosing_function": "Child",
        },
        {"kind": "class", "name": "Base", "file_id": 1},
        {"kind": "interface", "name": "Renderable", "file_id": 2},
    ]

    graph = resolve_graph(entities, [], ["child.py", "base.py", "renderable.py"])

    assert [
        edge for edge in graph["edges"] if edge["kind"] in ("extends", "implements")
    ] == [
        {
            "from": 0,
            "to": {"target": "entity", "id": 3},
            "kind": "extends",
            "resolved": True,
            "from_entity": 0,
        },
        {
            "from": 0,
            "to": {"target": "entity", "id": 4},
            "kind": "implements",
            "resolved": True,
            "from_entity": 0,
        },
    ]


def test_leaves_unknown_or_ambiguous_hierarchy_targets_unresolved():
    entities = [
        {"kind": "class", "name": "Child", "file_id": 0},
        {
            "kind": "extends",
            "name": "Missing",
            "file_id": 0,
            "enclosing_function": "Child",
        },
        {
            "kind": "implements",
            "name": "Duplicate",
            "file_id": 0,
            "enclosing_function": "Child",
        },
        {"kind": "class", "name": "Duplicate", "file_id": 1},
        {"kind": "interface", "name": "Duplicate", "file_id": 2},
    ]

    graph = resolve_graph(entities, [], ["child.py", "one.py", "two.py"])

    hierarchy_edges = [
        edge for edge in graph["edges"] if edge["kind"] in ("extends", "implements")
    ]
    assert [edge["to"] for edge in hierarchy_edges] == [
        {"target": "unknown"},
        {"target": "unknown"},
    ]
    assert [edge["resolved"] for edge in hierarchy_edges] == [False, False]
