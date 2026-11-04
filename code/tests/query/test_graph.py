from __future__ import annotations

import sqlite3

import pytest
from varde_code.query import dispatch
from varde_code.query.graph import Graph, dependencies
from varde_code.query.params import QueryError


@pytest.fixture
def graph_db(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    db = tmp_path / "index.db"
    conn = sqlite3.connect(db)
    schema = (
        "\n"
        "        CREATE TABLE files(id INTEGER PRIMARY KEY,path TEXT,"
        "is_test_path INTEGER,"
        "complexity INTEGER);\n"
        "        CREATE TABLE entities(\n"
        "            id INTEGER PRIMARY KEY, kind INTEGER, name TEXT, "
        "file_id INTEGER,\n"
        "            start_byte INTEGER, end_byte INTEGER, start_line INTEGER, "
        "start_col INTEGER,\n"
        "            end_line INTEGER, end_col INTEGER, enclosing_function TEXT, "
        "method TEXT,\n"
        "            path TEXT, owner_type TEXT\n"
        "        );\n"
        "        CREATE TABLE symbols(id INTEGER PRIMARY KEY,kind INTEGER,name TEXT,"
        "file_id INTEGER,\n"
        "            start_byte INTEGER,end_byte INTEGER,start_line INTEGER,"
        "start_col INTEGER,end_line INTEGER,end_col INTEGER);\n"
        "        CREATE TABLE resolved_edges(id INTEGER PRIMARY KEY,"
        "from_file_id INTEGER,to_file_id INTEGER,\n"
        "            from_entity_id INTEGER,to_entity_id INTEGER,kind INTEGER,"
        "resolved INTEGER);\n"
    )
    conn.executescript(schema)
    for file_id, path in enumerate(("a.py", "b.py", "c.py", "d.py"), start=1):
        conn.execute("INSERT INTO files VALUES (?, ?, 0, 1)", (file_id, path))
    # b -> a, c -> b, d -> a, and a -> c form a cycle; unresolved edges are ignored.
    for edge in ((1, 2, 1, 1), (2, 3, 2, 1), (3, 1, 3, 1), (4, 4, 1, 1), (5, 4, 2, 0)):
        conn.execute(
            "INSERT INTO resolved_edges VALUES (?, ?, ?, NULL, NULL, 1, ?)", edge
        )
    conn.executemany(
        (
            "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, 1, 0, 1, 10, ?, "
            "NULL, NULL, NULL)"
        ),
        [
            (1, 0, "target", 1, 0, 10, None),
            (2, 0, "caller", 2, 0, 20, None),
            (3, 6, "target", 2, 5, 10, None),
            (4, 1, "Parent", 1, 30, 40, None),
            (5, 1, "Child", 2, 30, 40, None),
            (6, 15, "Parent", 2, 41, 45, "Child"),
        ],
    )
    conn.execute("INSERT INTO symbols VALUES (1, 0, 'target', 1, 0, 10, 1, 0, 1, 10)")
    conn.execute("INSERT INTO resolved_edges VALUES (6, 2, 1, 3, 1, 0, 1)")
    conn.commit()
    conn.close()
    return {"repoRoot": str(root), "dbPath": str(db)}


def test_graph_walks_are_sorted_depth_limited_and_cycle_safe(graph_db):
    assert dependencies({**graph_db, "filePath": "a.py"}) == ["b.py", "c.py"]
    assert dependencies({**graph_db, "filePath": "a.py", "direction": "incoming"}) == [
        "b.py",
        "c.py",
        "d.py",
    ]
    assert dependencies({**graph_db, "filePath": "a.py", "maxDepth": 1}) == ["c.py"]
    assert dependencies(
        {**graph_db, "filePath": "a.py", "direction": "incoming", "maxDepth": 1}
    ) == ["b.py", "d.py"]
    assert dependencies({**graph_db, "filePath": "a.py", "maxDepth": 0}) == []


def test_graph_model_serialization_round_trips():
    graph = Graph(
        paths={1: "a", 2: "b", 3: "c"}, out={1: [2], 2: [3]}, inc={2: [1], 3: [2]}
    )

    assert Graph.from_dict(graph.to_dict()) == graph


def test_other_graph_modes_and_errors(graph_db, monkeypatch):
    from varde_code.query import graph as graph_module

    monkeypatch.setattr("varde_code.query.content_stale", lambda *_a: False)

    assert dispatch("dependents", {**graph_db, "filePath": "a.py"})["data"] == [
        "b.py",
        "c.py",
        "d.py",
    ]
    assert dispatch("blast_radius", {**graph_db, "filePath": "a.py"})["data"] == [
        "b.py",
        "c.py",
        "d.py",
    ]
    assert dispatch(
        "explore", {**graph_db, "query": {"params": {"input": "target", "maxItems": 1}}}
    )["data"] == {
        "input": "target",
        "resolvedVia": "symbol_exact",
        "seedFiles": ["a.py"],
        "reachable": ["b.py"],
    }
    impact = dispatch("symbol_blast_radius", {**graph_db, "name": "target"})["data"]
    assert impact["declaring_file"] == "a.py"
    assert impact["blast_radius"] == ["b.py"]
    hierarchy = dispatch("type_hierarchy", {**graph_db, "name": "Parent"})["data"]
    assert [item["name"] for item in hierarchy["subtypes"]] == ["Child"]
    assert graph_module is not None
    with pytest.raises(QueryError) as error:
        dependencies({**graph_db, "filePath": "missing.py"})
    assert error.value.code == "not_found"
