from __future__ import annotations

import sqlite3

import pytest
from varde_code.index.db import SCHEMA_VERSION
from varde_code.query import dispatch
from varde_code.query.modes import registered_modes
from varde_code.query.params import QueryError
from varde_code.query.simple import (
    filter_symbols,
    find_imports,
    get_symbol,
    symbols_in_file,
)
from varde_code.query.simple import (
    tests_for_file as query_tests_for_file,
)


@pytest.fixture
def query_db(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src/a.py").write_text("def alpha(): return 1\n")
    (root / "tests/test_a.py").write_text("from src.a import alpha\n")
    db = tmp_path / "index.db"
    conn = sqlite3.connect(db)
    schema = (
        "\n"
        "        CREATE TABLE files(id INTEGER PRIMARY KEY,path TEXT,is_test_path "
        "INTEGER,complexity INTEGER,rev INTEGER DEFAULT 1);\n"
        "        CREATE TABLE entities(id INTEGER PRIMARY KEY,kind INTEGER,name TEXT,"
        "file_id INTEGER,start_byte INTEGER,end_byte INTEGER,start_line INTEGER,"
        "start_col INTEGER,end_line INTEGER,end_col INTEGER);\n"
        "        CREATE TABLE symbols(id INTEGER PRIMARY KEY,kind INTEGER,name TEXT,"
        "file_id INTEGER,start_byte INTEGER,end_byte INTEGER,start_line INTEGER,"
        "start_col INTEGER,end_line INTEGER,end_col INTEGER);\n"
        "        CREATE TABLE resolved_edges(id INTEGER PRIMARY KEY,from_file_id "
        "INTEGER,"
        "to_file_id INTEGER,kind INTEGER,resolved INTEGER);\n"
    )
    conn.executescript(schema)
    conn.execute(
        "INSERT INTO files(id,path,is_test_path,complexity) VALUES (1, ?, 0, 1)",
        (str(root / "src/a.py"),),
    )
    conn.execute(
        "INSERT INTO files(id,path,is_test_path,complexity) VALUES (2, ?, 1, 0)",
        (str(root / "tests/test_a.py"),),
    )
    conn.execute("INSERT INTO entities VALUES (1,0,'alpha',1,4,9,1,4,1,9)")
    conn.execute("INSERT INTO symbols VALUES (1,0,'alpha',1,4,9,1,4,1,9)")
    conn.execute("INSERT INTO resolved_edges VALUES (1,2,1,1,1)")
    conn.commit()
    conn.close()
    return {"repoRoot": str(root), "dbPath": str(db), "root": root}


def test_symbols_get_and_filter(query_db):
    value = {**query_db, "filePath": "src/a.py"}
    assert [item["name"] for item in symbols_in_file(value)] == ["alpha", "alpha"]
    assert get_symbol({**query_db, "name": "alpha"})["kind"] == "function"
    assert [item["kind"] for item in filter_symbols(query_db)] == [
        "function",
        "binding",
    ]
    assert [
        item["kind"] for item in filter_symbols({**query_db, "kind": "function"})
    ] == ["function"]


def test_imports_coverage_and_unknown_file(query_db):
    value = {**query_db, "filePath": "src/a.py"}
    assert find_imports(value) == []
    assert query_tests_for_file(value) == [str(query_db["root"] / "tests/test_a.py")]
    with pytest.raises(QueryError) as error:
        symbols_in_file({**query_db, "filePath": "missing.py"})
    assert error.value.code == "not_found"


def test_simple_handlers_register_with_dispatch(query_db, monkeypatch):
    monkeypatch.setattr("varde_code.query.content_stale", lambda *_a: False)
    result = dispatch("find_imports", {**query_db, "filePath": "src/a.py"})
    assert result["ok"] is True
    assert result["data"] == []


def test_index_missing_message_names_build_and_packs(tmp_path):
    result = dispatch(
        "symbols_in_file",
        {
            "repoRoot": str(tmp_path),
            "dbPath": str(tmp_path / "no.db"),
            "filePath": "a.py",
        },
    )

    message = result["data"]["error"]["message"]
    assert result["data"]["error"]["code"] == "index_missing"
    assert "varde map build" in message
    assert "packs" in message
    assert "setup watch" not in message


def test_package_import_registers_every_map_mode(query_db):
    expected = {
        "batch",
        "symbols_in_file",
        "symbols_in_files",
        "get_symbol",
        "dependencies",
        "dependents",
        "tests_for_file",
        "hotspots",
        "clusters",
        "map_file",
        "map_symbol",
        "map_path",
        "explore",
        "blast_radius",
        "symbol_blast_radius",
        "detect_changes",
        "find_imports",
        "type_hierarchy",
        "filter_symbols",
        "find_pattern",
        "context_pack",
        "nav_map",
        "slice_state",
    }
    assert expected <= set(registered_modes())
    assert "foundational_files" not in registered_modes()

    result = dispatch(
        "symbols_in_files", {**query_db, "filePaths": ["src/a.py", "missing.py"]}
    )
    assert result["ok"] is True
    assert result["data"]["src/a.py"][0]["name"] == "alpha"
    assert result["data"]["missing.py"]["error"]["code"] == "not_found"


def test_slice_state_dispatches_to_read_only_index_state(query_db, monkeypatch):
    conn = sqlite3.connect(query_db["dbPath"])
    slice_schema = (
        "\n"
        "        CREATE TABLE slice_state(slice TEXT, built_through_rev INTEGER, "
        "schema_version INTEGER);\n"
        "        CREATE TABLE slice_meta(key TEXT, value INTEGER);\n"
    )
    conn.executescript(slice_schema)
    conn.execute("INSERT INTO slice_state VALUES ('imports', 1, ?)", (SCHEMA_VERSION,))
    conn.execute("INSERT INTO slice_meta VALUES ('next_rev', 2)")
    conn.commit()
    conn.close()

    class TestService:
        def dump_state(self, root):
            assert root == query_db["root"]
            return {
                "db_path": query_db["dbPath"],
                "max_rev": 1,
                "next_rev": 2,
                "slices": {
                    "imports": {"built_through_rev": 1, "stale": False},
                    "edges": {"built_through_rev": None, "stale": True},
                    "global": {"built_through_rev": None, "stale": True},
                },
            }

    monkeypatch.setattr("varde_code.query.modes._INDEX_SERVICE", TestService())
    result = dispatch(
        "slice_state", {"dbPath": query_db["dbPath"], "repoRoot": str(query_db["root"])}
    )

    assert result["ok"] is True
    assert result["data"] == {
        "db_path": query_db["dbPath"],
        "max_rev": 1,
        "next_rev": 2,
        "slices": {
            "imports": {"built_through_rev": 1, "stale": False},
            "edges": {"built_through_rev": None, "stale": True},
            "global": {"built_through_rev": None, "stale": True},
        },
    }
