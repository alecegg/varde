from __future__ import annotations

import sqlite3

from varde_code.model import EntityKind, RoleTag
from varde_code.query.entrypoints import (
    Entrypoint,
    detect_node_entrypoints,
    detect_process_mains,
    detect_routes,
    detect_sveltekit_pages,
    detect_sveltekit_server_routes,
    detect_tagged_entrypoints,
    is_bootstrap_filename,
    join_route_path,
    process_main_name_for_path,
)


def database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE files(id INTEGER PRIMARY KEY, path TEXT, is_test_path INTEGER);
        CREATE TABLE entities(
            id INTEGER PRIMARY KEY, file_id INTEGER, kind INTEGER, name TEXT,
            owner_type TEXT, method TEXT, path TEXT
        );
    """)
    return conn


def test_bootstrap_and_language_main_conventions() -> None:
    assert is_bootstrap_filename(r"src\\main.py")
    assert not is_bootstrap_filename("src/Main.py")
    assert process_main_name_for_path("src/main.cpp") == "main"
    assert process_main_name_for_path("src/Program.cs") == "Main"
    assert process_main_name_for_path("src/main.py") is None


def test_join_route_path_normalizes_and_drops_empty_parts() -> None:
    assert join_route_path(" /api/ ", "/users/{id}/") == "/api/users/{id}"
    assert join_route_path("/", "") is None


def test_detect_routes_resolves_handler_and_omits_noise() -> None:
    conn = database()
    conn.executemany(
        "INSERT INTO files VALUES (?, ?, ?)",
        [
            (1, "/repo/src/server.ts", 0),
            (2, "/repo/tests/app.ts", 1),
        ],
    )
    conn.executemany(
        "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (10, 1, 0, "listUsers", None, None, None),
            (11, 1, 13, "route", "listUsers", "get", "/users"),
            (12, 2, 13, "route", None, "get", "/test"),
        ],
    )
    results = detect_routes(conn)
    assert results == [
        Entrypoint(
            10,
            "/repo/src/server.ts",
            "GET /users",
            RoleTag.ROUTE_HANDLER,
            True,
            "GET",
            "/users",
        )
    ]


def test_detect_process_mains_filters_by_language_and_path() -> None:
    conn = database()
    conn.executemany(
        "INSERT INTO files VALUES (?, ?, ?)",
        [
            (1, "/repo/src/main.rs", 0),
            (2, "/repo/src/main.py", 0),
            (3, "/repo/tests/main.go", 1),
        ],
    )
    conn.executemany(
        "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (10, 1, 0, "main", None, None, None),
            (11, 2, 0, "main", None, None, None),
            (12, 3, 0, "main", None, None, None),
        ],
    )
    result = detect_process_mains(conn)
    assert [(item.file, item.symbol) for item in result] == [
        ("/repo/src/main.rs", "main")
    ]
    assert result[0].role is RoleTag.PROCESS_MAIN


def test_detect_node_and_sveltekit_entrypoints(tmp_path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    entrypoint = (
        "export function main() {}\nif (import.meta.url === "
        "pathToFileURL(process.argv[1]).href) { main(); }\n"
    )
    (root / "src/cli.ts").write_text(entrypoint)
    conn = database()
    conn.executemany(
        "INSERT INTO files VALUES (?, ?, ?)",
        [
            (1, "src/cli.ts", 0),
            (2, "src/routes/(admin)/users/+page.svelte", 0),
            (3, "src/routes/users/+server.ts", 0),
        ],
    )
    conn.executemany(
        "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (10, 1, EntityKind.FUNCTION.as_i64(), "main", None, None, None),
            (11, 3, EntityKind.FUNCTION.as_i64(), "GET", None, None, None),
            (12, 3, EntityKind.EXPORT.as_i64(), "GET", None, None, None),
        ],
    )
    conn.execute("ALTER TABLE entities ADD COLUMN role_tag TEXT")
    conn.execute(
        "UPDATE entities SET role_tag=? WHERE id=10",
        (RoleTag.BACKGROUND_JOB.value,),
    )

    tagged = detect_tagged_entrypoints(conn)
    node_entries = detect_node_entrypoints(conn, root)
    server_routes = detect_sveltekit_server_routes(conn)
    pages = detect_sveltekit_pages(conn)

    assert [(entry.symbol, entry.role) for entry in node_entries] == [
        ("main", RoleTag.PROCESS_MAIN)
    ]
    assert [(entry.symbol, entry.role) for entry in tagged] == [
        ("main", RoleTag.BACKGROUND_JOB)
    ]
    assert [(entry.symbol, entry.method, entry.path) for entry in server_routes] == [
        ("GET", "GET", "/users")
    ]
    assert pages == [
        {
            "file": "src/routes/(admin)/users/+page.svelte",
            "symbol": "+page",
            "role": "page_component",
            "path": "/users",
        }
    ]
