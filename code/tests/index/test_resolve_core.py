from typing import Any, cast

from varde_code.index.resolve import resolve


def resolve_graph(*args: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", resolve(*args))


from varde_code.index.resolve.core import _FileIndex, _match_import  # noqa: E402, RUF100 - source tree must be added to sys.path first


def test_relative_import_strips_edge_backslashes() -> None:
    files = ["src/main.py", "src/util.py"]
    assert _match_import(".\\util\\", 0, _FileIndex(files)) == 1


def test_resolves_relative_import_and_imported_call():
    files = ["src/main.py", "src/util.py"]
    entities = [
        {"kind": "import", "name": ".util", "file_id": 0},
        {"kind": "call", "name": "helper", "file_id": 0},
        {"kind": "function", "name": "helper", "file_id": 1},
    ]

    graph = resolve_graph(entities, [], files)

    assert graph["nodes"] == [
        {"path": "src/main.py", "community_id": 0, "fan_in": 0, "fan_out": 2},
        {"path": "src/util.py", "community_id": 0, "fan_in": 2, "fan_out": 0},
    ]
    assert graph["edges"] == [
        {
            "from": 0,
            "to": {"target": "file", "id": 1},
            "kind": "import",
            "resolved": True,
            "from_entity": 0,
        },
        {
            "from": 0,
            "to": {"target": "entity", "id": 2},
            "kind": "call",
            "resolved": True,
            "from_entity": 1,
        },
    ]
    assert graph["communities"] == [
        {"id": 0, "members": ["src/main.py", "src/util.py"]}
    ]


def test_leaves_dangling_import_unresolved():
    graph = resolve_graph(
        [{"kind": "import", "name": "missing", "file_id": 0}],
        [],
        ["src/main.py"],
    )

    assert graph["edges"][0]["to"] == {"target": "unknown"}
    assert graph["edges"][0]["resolved"] is False
