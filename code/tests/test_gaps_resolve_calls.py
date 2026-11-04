from typing import Any, cast

from varde_code.index.resolve import resolve


def resolve_graph(*args: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", resolve(*args))


def _call_target(entities, files):
    edges = resolve_graph(entities, [], files)["edges"]
    call = next(edge for edge in edges if edge["kind"] == "call")
    return call["to"]


def test_module_receiver_call_uses_import_binding():
    entities = [
        {"kind": "import", "name": "helper", "owner_type": "helper", "file_id": 0},
        {"kind": "call", "name": "helper.do_work()", "file_id": 0},
        {"kind": "function", "name": "do_work", "file_id": 1},
    ]

    assert _call_target(entities, ["src/main.py", "src/helper.py"]) == {
        "target": "entity",
        "id": 2,
    }


def test_java_unique_definition_resolves_across_namespace_files():
    entities = [
        {"kind": "call", "name": "loadConfig()", "file_id": 0},
        {"kind": "function", "name": "loadConfig", "file_id": 1},
    ]

    assert _call_target(entities, ["src/App.java", "src/Config.java"]) == {
        "target": "entity",
        "id": 1,
    }


def test_typed_interface_receiver_resolves_unique_implementation():
    entities = [
        {"kind": "call", "name": "service.fetch()", "file_id": 0},
        {
            "kind": "type_ref",
            "name": "IFetcher",
            "enclosing_function": "service",
            "file_id": 0,
        },
        {"kind": "interface", "name": "IFetcher", "file_id": 1},
        {"kind": "class", "name": "Fetcher", "file_id": 2},
        {
            "kind": "implements",
            "name": "IFetcher",
            "enclosing_function": "Fetcher",
            "file_id": 2,
        },
        {
            "kind": "function",
            "name": "fetch",
            "owner_type": "Fetcher",
            "file_id": 2,
        },
        {
            "kind": "class",
            "name": "Other",
            "file_id": 3,
        },
        {
            "kind": "function",
            "name": "fetch",
            "owner_type": "Other",
            "file_id": 3,
        },
    ]

    assert _call_target(
        entities,
        ["src/App.java", "src/IFetcher.java", "src/Fetcher.java", "src/Other.java"],
    ) == {"target": "entity", "id": 5}
