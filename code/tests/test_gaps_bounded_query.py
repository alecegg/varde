from __future__ import annotations

import sqlite3

from varde_code.query.module_layers import compute_module_layers
from varde_code.query.nav_map import (
    _budget_nav_map,
    _module_layers_section,
    _resolved_file_edges,
)


def test_nav_map_module_layers_include_all_resolved_edge_kinds(tmp_path):
    db_path = tmp_path / "index.db"
    with sqlite3.connect(db_path) as db:
        db.executescript("""
            CREATE TABLE files(id INTEGER PRIMARY KEY, path TEXT);
            CREATE TABLE resolved_edges(
                from_file_id INTEGER, to_file_id INTEGER, resolved INTEGER, kind INTEGER
            );
            INSERT INTO files VALUES (1, 'src/a.py'), (2, 'src/b.py');
            INSERT INTO resolved_edges VALUES
                (1, 2, 1, 0), (1, 2, 1, 1), (2, 1, 0, 2);
        """)

        assert _resolved_file_edges(db) == [
            ("src/a.py", "src/b.py"),
            ("src/a.py", "src/b.py"),
        ]


def test_nav_map_module_layers_use_query_contract_field_names():
    layers = compute_module_layers(
        [
            ("src/a/file.py", "src/b/file.py"),
            ("src/a/other.py", "src/b/other.py"),
            ("src/a/third.py", "src/b/third.py"),
        ]
    )

    assert _module_layers_section(layers) == {
        "edges": [
            {
                "from_module": "src/a",
                "to_module": "src/b",
                "crossing_files": 3,
            }
        ],
        "cycles": [],
    }


def test_nav_map_budget_truncates_module_layers_and_records_totals():
    data = {
        "entrypoints": [{"name": "main"}],
        "foundational_files": [],
        "module_layers": {
            "edges": [
                {"from_module": "src/a", "to_module": "src/b", "crossing_files": 3}
            ],
            "cycles": [],
        },
        "subsystems": [],
        "symbols": [],
        "flows": [],
        "hotspots": [],
    }

    guide = _budget_nav_map(data, 1)

    assert data["module_layers"]["edges"] == []
    assert guide["truncated"]["module_layers.edges"] == {
        "shown": 0,
        "total": 1,
        "more": (
            "raise maxTokensEstimate; module_layers holds the resolved "
            "module-dependency graph"
        ),
    }
    assert guide["minimumBudgetTokens"] > guide["budgetTokens"]
