from __future__ import annotations

import sqlite3
from pathlib import Path

from varde_code.query.mapping import context_pack
from varde_code.query.nav_map import nav_map


def _query_db(path):
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE files(
                id INTEGER PRIMARY KEY, path TEXT, complexity INTEGER, churn INTEGER,
                fan_in INTEGER DEFAULT 0, fan_out INTEGER DEFAULT 0,
                community_id INTEGER DEFAULT 0, is_test_path INTEGER DEFAULT 0
            );
            CREATE TABLE entities(
                id INTEGER PRIMARY KEY, name TEXT, kind INTEGER, file_id INTEGER,
                start_line INTEGER, end_line INTEGER, role_tag TEXT,
                owner_type TEXT, enclosing_function TEXT, method TEXT, path TEXT
            );
            CREATE TABLE resolved_edges(
                id INTEGER PRIMARY KEY, from_file_id INTEGER, to_file_id INTEGER,
                from_entity_id INTEGER, to_entity_id INTEGER, kind INTEGER,
                resolved INTEGER
            );
            CREATE TABLE community_members(community_id INTEGER, file_id INTEGER);
            INSERT INTO files(id, path, complexity, churn, fan_in, is_test_path) VALUES
                (1, 'src/app.py', 2, 0, 1, 0),
                (2, 'src/helper.py', 2, 0, 1, 0),
                (3, 'tests/test_app.py', 0, 0, 0, 1);
            INSERT INTO entities(id, name, kind, file_id, start_line, end_line) VALUES
                (1, 'main', 0, 1, 4, 5),
                (2, 'render', 0, 2, 1, 2);
            INSERT INTO resolved_edges(
                from_file_id, to_file_id, from_entity_id, to_entity_id, kind, resolved
            ) VALUES (1, 2, 1, 2, 0, 1);
            INSERT INTO community_members VALUES (2, 1), (2, 2), (2, 3);
        """)


def test_context_pack_matches_exact_symbol_and_one_hop_neighbor(tmp_path):
    root = Path.cwd()
    db_path = tmp_path / "index.db"
    _query_db(db_path)

    result = context_pack(
        {"repoRoot": str(root), "dbPath": str(db_path), "query": "main"}
    )

    assert result["files"] == [
        {"path": "src/app.py", "relevance": "seed"},
        {"path": "src/helper.py", "relevance": "neighbor"},
    ]
    assert result["symbols"] == [
        {
            "name": "main",
            "filePath": "src/app.py",
            "kind": "function",
            "span": {"start_line": 4, "end_line": 5},
        }
    ]
    assert result["readingOrder"] == ["src/app.py", "src/helper.py"]


def test_nav_map_qualifies_community_id_and_excludes_test_files(tmp_path):
    db_path = tmp_path / "index.db"
    _query_db(db_path)

    result = nav_map({"repoRoot": str(tmp_path), "dbPath": str(db_path)})

    assert result["subsystems"] == [
        {"id": 2, "name": "src", "members": ["src/app.py", "src/helper.py"]}
    ]
