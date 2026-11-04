from typing import Any, cast

from varde_code.index.resolve import resolve


def resolve_graph(*args: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", resolve(*args))


def test_import_resolution_finds_unique_local_targets():
    files = [
        "src/main.py",
        "src/util.py",
        "src/pkg/__init__.py",
        "src/pkg/item.py",
        "other/util.py",
        "src/util.js",
        "src/pkg/item.pyi",
        "src/pkg/nested/leaf.py",
    ]
    names = [".util", ".pkg", ".pkg.item", "..pkg.item", "pkg.item", "missing"]
    entities = [{"kind": "import", "name": name, "file_id": 0} for name in names]
    result = resolve_graph(entities, [], files)

    assert [edge["to"].get("id") for edge in result["edges"]] == [
        1,
        2,
        None,
        None,
        3,
        None,
    ]
