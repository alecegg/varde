from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.build import build
from varde_code.index.paths import repo_db_path
from varde_code.query.foundational_files import leaderboard
from varde_code.query.mapping import context_pack, map_file, map_path
from varde_code.query.nav_map import nav_map, nav_map_text
from varde_code.query.params import QueryError
from varde_code.query.symbols_section import is_accessor
from varde_code.query.symbols_section import leaderboard as symbol_leaderboard


def test_foundational_leaderboard_counts_distinct_dependents() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE files(
            id INTEGER PRIMARY KEY,path TEXT,fan_in INTEGER,is_test_path INTEGER \
DEFAULT 0
        );
        CREATE TABLE resolved_edges(
            from_file_id INTEGER,to_file_id INTEGER,resolved INTEGER
        );
        CREATE TABLE entities(file_id INTEGER,name TEXT,kind INTEGER);
        INSERT INTO files VALUES
            (1,'src/core.py',5,0),(2,'src/a.py',0,0),(3,'src/b.py',0,0);
        INSERT INTO resolved_edges VALUES (2,1,1),(2,1,1),(2,1,1),(3,1,1),(3,1,1);
    """)
    result = leaderboard(conn)
    assert result == [
        {
            "file": "src/core.py",
            "count": 5,
            "dependents": 2,
            "why": "depended on by 2 other files (5 references total) in the repo",
        }
    ]


def test_symbol_leaderboard_excludes_entrypoints_and_accessor_names() -> None:
    assert is_accessor("getName")
    assert not is_accessor("issue")
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE files(
            id INTEGER PRIMARY KEY,path TEXT,is_test_path INTEGER DEFAULT 0
        );
        CREATE TABLE entities(
            id INTEGER PRIMARY KEY,file_id INTEGER,name TEXT,owner_type TEXT,\
kind INTEGER
        );
        CREATE TABLE resolved_edges(
            id INTEGER PRIMARY KEY,to_entity_id INTEGER,resolved INTEGER,kind INTEGER,
            from_file_id INTEGER
        );
        INSERT INTO files VALUES(1,'src/core.py',0),(2,'src/a.py',0);
        INSERT INTO entities VALUES
            (10,1,'core_api',NULL,0),(11,1,'getName',NULL,0);
        INSERT INTO resolved_edges VALUES
            (1,10,1,0,2),(2,11,1,0,2);
    """)
    assert symbol_leaderboard(conn, {10}) == []


def test_nav_map_text_formats_success_data_and_preserves_errors() -> None:
    assert nav_map_text(
        {
            "ok": True,
            "data": {
                "entrypoints": [],
                "foundational_files": [],
                "module_layers": {"edges": [], "cycles": []},
                "subsystems": [],
                "symbols": [],
                "flows": [],
                "hotspots": [],
            },
        },
        False,
    ).startswith("## entrypoints\n(none)")
    assert (
        nav_map_text({"ok": False, "data": {"error": "bad"}}, False)
        == '{"ok":false,"data":{"error":"bad"}}'
    )


def test_mapping_modes_and_nav_map_read_a_native_index(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src/core.py").write_text(
        "def answer():\n    return 42\n", encoding="utf-8"
    )
    (root / "src/app.py").write_text(
        "from core import answer\n\n\ndef main():\n    return answer()\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    build(root, CodeExtractionProvider())
    input = {"repoRoot": str(root), "dbPath": str(repo_db_path(root))}
    app_path = (root / "src/app.py").as_posix()
    mapped = map_file({**input, "filePath": app_path})
    assert mapped["path"] == app_path
    assert map_path(
        {
            **input,
            "sourceFile": app_path,
            "targetFile": (root / "src/core.py").as_posix(),
        }
    ) == [app_path, (root / "src/core.py").as_posix()]
    data = nav_map(input)
    assert tuple(data) == (
        "entrypoints",
        "foundational_files",
        "module_layers",
        "subsystems",
        "symbols",
        "flows",
        "hotspots",
        "guide",
    )


def test_context_pack_fuses_docstring_matches_and_keeps_structural_mode(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src/tides.py").write_text(
        (
            'def predict():\n    """Lunar eclipses perturb tidal harmonics."""\n'
            "    return 1\n"
        ),
        encoding="utf-8",
    )
    (root / "src/predict_a.py").write_text(
        "def predict_a():\n    return 2\n", encoding="utf-8"
    )
    (root / "src/predict_b.py").write_text(
        "def predict_b():\n    return 3\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    build(root, CodeExtractionProvider())
    query = "lunar eclipses perturb tidal harmonics"
    base = {"repoRoot": str(root), "dbPath": str(repo_db_path(root)), "query": query}

    default_result = context_pack(base)
    assert default_result["files"][0]["path"].endswith("src/tides.py")
    assert any(item["name"] == "predict" for item in default_result["symbols"])
    structural_query = {**base, "query": "predict", "rankingMode": "structural"}
    fallback_query = {**base, "query": "predict", "rankingMode": "fallback"}
    default_paths = [
        item["path"] for item in context_pack({**base, "query": "predict"})["files"]
    ]
    structural_paths = [
        item["path"] for item in context_pack(structural_query)["files"]
    ]
    assert default_paths == structural_paths
    assert [
        item["path"] for item in context_pack(fallback_query)["files"]
    ] == structural_paths
    try:
        context_pack({**base, "rankingMode": "fused"})
    except QueryError as exc:
        assert exc.code == "invalid_input"
    else:
        raise AssertionError("invalid rankingMode was accepted")
