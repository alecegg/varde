from __future__ import annotations

import sqlite3
from typing import Any, cast

from varde_code.model import Community, RoleTag
from varde_code.query.entrypoints import Entrypoint
from varde_code.query.flows import build_flows
from varde_code.query.module_layers import compute_module_layers
from varde_code.query.subsystems import name_clusters


def test_module_layers_threshold_and_cycle() -> None:
    edges = []
    for i in range(3):
        edges.extend(
            [
                (f"a/a{i}.py", f"b/b{i}.py"),
                (f"b/b{i}.py", f"c/c{i}.py"),
                (f"c/c{i}.py", f"a/a{i}.py"),
            ]
        )

    result = compute_module_layers(edges)

    assert [(e.from_module, e.to_module, e.crossing_files) for e in result.edges] == [
        ("a", "b", 3),
        ("b", "c", 3),
        ("c", "a", 3),
    ]
    assert {tuple(sorted(cycle)) for cycle in result.cycles} == {("a", "b", "c")}
    assert compute_module_layers(edges[:2]).edges == []


def test_subsystems_filter_noise_name_and_disambiguate() -> None:
    clusters = [
        Community(
            1, ["src/auth/a.py", "src/auth/b.py", "src/auth/node_modules/generated.py"]
        ),
        Community(2, ["src/auth/c.py", "src/auth/d.py"]),
        Community(3, ["src/single.py"]),
    ]

    result = name_clusters(clusters, {})

    assert [(item.id, item.name, item.members) for item in result] == [
        (1, "auth/a", ["src/auth/a.py", "src/auth/b.py"]),
        (2, "auth/c", ["src/auth/c.py", "src/auth/d.py"]),
    ]


def test_flows_build_reachable_trees_and_cross_entrypoint_backrefs() -> None:
    conn = sqlite3.connect(":memory:")
    script = (
        """
        CREATE TABLE files(id INTEGER PRIMARY KEY, path TEXT);
        CREATE TABLE entities(
            id INTEGER PRIMARY KEY, file_id INTEGER, name TEXT,
            owner_type TEXT, enclosing_function TEXT
        );
        CREATE TABLE resolved_edges(
            id INTEGER PRIMARY KEY, kind INTEGER, resolved INTEGER,
            from_entity_id INTEGER, to_entity_id INTEGER
        );
        INSERT INTO files VALUES """
        "(1, 'src/main.py'), (2, 'src/lib.py'), (3, 'src/shared.py');\n"
        """
        INSERT INTO entities VALUES
            (1, 1, 'main', NULL, NULL), (2, 2, 'work', NULL, NULL),
            (3, 3, 'shared', NULL, NULL), (10, 1, 'call_work', NULL, 'main'),
            (11, 2, 'call_shared', NULL, 'work'), (12, 4, 'call_shared', NULL, 'other');
        INSERT INTO resolved_edges VALUES
            (1, 0, 1, 10, 2), (2, 0, 1, 11, 3), (3, 0, 1, 12, 3);
    """
    )
    conn.executescript(script)
    # A second entrypoint reaches the same utility through its own caller.
    conn.execute("INSERT INTO files VALUES (4, 'src/other.py')")
    conn.execute("INSERT INTO entities VALUES (4, 4, 'other', NULL, NULL)")

    trees = build_flows(
        conn,
        [
            Entrypoint(1, "src/main.py", "main", RoleTag.PROCESS_MAIN),
            Entrypoint(4, "src/other.py", "other", RoleTag.PROCESS_MAIN),
        ],
    )

    first_tree = cast("dict[str, Any]", trees[0].to_json())
    second_tree = cast("dict[str, Any]", trees[1].to_json())
    assert first_tree["root"]["children"][0]["children"][0]["symbol"] == "shared"
    assert second_tree["root"]["children"][0]["backref_to"] == {
        "entrypoint": "main",
        "file": "src/shared.py",
        "symbol": "shared",
        "entity_id": 3,
    }
