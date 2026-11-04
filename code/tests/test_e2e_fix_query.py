from __future__ import annotations

import sqlite3

from varde_code.query import dispatch
from varde_code.query.graph import dependencies
from varde_code.query.output import compact, paginate


def test_query_modes_use_default_and_captured_page_sizes():
    values = list(range(125))
    filtered, filtered_meta = paginate(values, {}, "filter_symbols")
    hotspots, hotspots_meta = paginate(values, {}, "hotspots")
    short_filter, short_filter_meta = paginate(values[:82], {}, "filter_symbols")
    symbols, symbols_meta = paginate(values, {}, "symbols_in_file")

    assert filtered == values[:100]
    assert hotspots == values[:100]
    assert short_filter == values[:82]
    assert short_filter_meta is None
    assert symbols == values[:100]
    assert filtered_meta is not None and hotspots_meta is not None
    assert symbols_meta is not None
    assert filtered_meta["limit"] == hotspots_meta["limit"] == 100
    assert filtered_meta["total"] == hotspots_meta["total"] == 125
    assert symbols_meta["limit"] == 100

    class Capture:
        def capture(self, input, source, label):
            return '{"handle":"H123","toc":[]}'

    captured_filter, captured_meta = paginate(values, {}, "filter_symbols", Capture())
    captured_hotspots, hotspots_page = paginate(values, {}, "hotspots", Capture())
    assert captured_filter == captured_hotspots == values[:20]
    assert captured_meta is not None and hotspots_page is not None
    assert captured_meta["limit"] == hotspots_page["limit"] == 20


def test_query_paths_are_repo_relative(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    alias = tmp_path / "repo-alias"
    alias.symlink_to(root, target_is_directory=True)
    absolute = str(root / "src" / "main.py")
    payload = {"file": absolute, "nested": [{"path": absolute}]}

    assert compact(payload, {"repoRoot": str(alias)}) is True
    assert payload == {"file": "src/main.py", "nested": [{"path": "src/main.py"}]}

    absolute_payload = {"file": absolute}
    assert compact(absolute_payload, {"repoRoot": "."}) is True
    assert absolute_payload == {"file": absolute}


def test_dependency_paths_remain_absolute(tmp_path):
    root = tmp_path / "repo"
    path = str(root / "src" / "helper.py")
    result = [path]

    assert compact(result, {"repoRoot": str(root), "mode": "dependencies"}) is True
    assert result == [path]


def test_path_lists_are_repo_relative(tmp_path):
    root = tmp_path / "repo"
    absolute = str(root / "src" / "helper.py")
    payload = {"clusters": [{"files": [absolute]}]}

    compact(payload, {"repoRoot": str(root)})

    assert payload == {"clusters": [{"files": ["src/helper.py"]}]}


def test_dependencies_falls_back_to_relative_python_imports(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    source = root / "src" / "app.py"
    target = root / "src" / "helper.py"
    source.write_text("from .helper import render\n")
    target.write_text("def render(): pass\n")
    db_path = tmp_path / "index.db"
    with sqlite3.connect(db_path) as db:
        db.executescript("""
            CREATE TABLE files(id INTEGER PRIMARY KEY, path TEXT);
            CREATE TABLE entities(
                id INTEGER PRIMARY KEY, kind INTEGER, name TEXT, file_id INTEGER
            );
            CREATE TABLE resolved_edges(
                id INTEGER PRIMARY KEY, from_file_id INTEGER, to_file_id INTEGER,
                kind INTEGER, resolved INTEGER, from_entity_id INTEGER,
                to_entity_id INTEGER
            );
        """)
        db.executemany(
            "INSERT INTO files VALUES (?, ?)",
            [(1, str(source)), (2, str(target))],
        )
        db.execute("INSERT INTO entities VALUES (1, 9, './helper', 1)")
        db.execute("INSERT INTO resolved_edges VALUES (1, 1, NULL, 1, 0, 1, NULL)")

    result = dependencies(
        {
            "dbPath": str(db_path),
            "repoRoot": str(root),
            "filePath": "src/app.py",
        }
    )

    assert result == [str(target)]


def test_slice_state_reads_python_index_without_injected_service(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    db_path = tmp_path / "config" / "code" / "repos-py" / "repo-1234" / "index.db"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as db:
        db.executescript("""
            CREATE TABLE files(rev INTEGER);
            CREATE TABLE slice_state(
                slice TEXT, built_through_rev INTEGER, schema_version INTEGER
            );
            CREATE TABLE slice_meta(key TEXT, value INTEGER);
            INSERT INTO files VALUES (1);
            INSERT INTO slice_state VALUES ('imports', 1, 20);
            INSERT INTO slice_state VALUES ('edges', 1, 20);
            INSERT INTO slice_state VALUES ('global', 1, 20);
            INSERT INTO slice_meta VALUES ('next_rev', 2);
        """)

    result = dispatch("slice_state", {"repoRoot": str(root), "dbPath": str(db_path)})

    assert result["ok"] is True
    assert result["data"] == {
        "db_path": str(db_path).replace("/repos-py/", "/repos/", 1),
        "max_rev": 1,
        "next_rev": 2,
        "slices": {
            name: {"built_through_rev": 1, "stale": False}
            for name in ("imports", "edges", "global")
        },
    }


def test_slice_state_uses_zero_next_rev_for_empty_index(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    db_path = tmp_path / "config" / "code" / "repos-py" / "repo-1234" / "index.db"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as db:
        db.executescript("""
            CREATE TABLE files(rev INTEGER);
            CREATE TABLE slice_state(
                slice TEXT, built_through_rev INTEGER, schema_version INTEGER
            );
            CREATE TABLE slice_meta(key TEXT, value INTEGER);
            INSERT INTO slice_state VALUES ('imports', 0, 19);
            INSERT INTO slice_state VALUES ('edges', 0, 19);
            INSERT INTO slice_state VALUES ('global', 0, 19);
            INSERT INTO slice_meta VALUES ('next_rev', 1);
        """)

    result = dispatch("slice_state", {"repoRoot": str(root), "dbPath": str(db_path)})

    assert result["data"]["max_rev"] == 0
    assert result["data"]["next_rev"] == 0
