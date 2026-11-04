"""Resolved file graph query modes."""

from __future__ import annotations

import sqlite3
from collections import deque
from pathlib import Path
from typing import Any

from varde_code.graph_model import Graph
from varde_code.model import EntityKind
from varde_code.parse import language_for_path

from .modes import register_mode
from .params import QueryError, opt_str, req_str
from .simple import _db, _file_id, _matches_path
from .symbol_impact import run as symbol_blast_radius


def _load_graph(conn: sqlite3.Connection) -> Graph:
    paths = {row[0]: row[1] for row in conn.execute("SELECT id,path FROM files")}
    out: dict[int, list[int]] = {}
    inc: dict[int, list[int]] = {}
    for source, target in conn.execute(
        "SELECT from_file_id,to_file_id FROM resolved_edges "
        "WHERE resolved=1 AND to_file_id IS NOT NULL"
    ):
        out.setdefault(source, []).append(target)
        inc.setdefault(target, []).append(source)
    return Graph(paths, out, inc)


def _walk(
    graph: Graph, start: int, forward: bool, max_depth: int | None = None
) -> list[int]:
    adjacency = graph.out if forward else graph.inc
    visited = {start}
    queue = deque([(start, 0)])
    while queue:
        node, depth = queue.popleft()
        if max_depth is not None and depth >= max_depth:
            continue
        for neighbor in adjacency.get(node, ()):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))
    return sorted(visited - {start})


def _paths(graph: Graph, ids: list[int]) -> list[str]:
    return sorted(graph.paths[node] for node in ids if node in graph.paths)


def _relative_or_original(path: str, root: Path) -> str:
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return path


def _opt_uint(value: dict[str, Any], key: str) -> int | None:
    number = value.get(key)
    return (
        number
        if isinstance(number, int) and not isinstance(number, bool) and number >= 0
        else None
    )


def dependencies(input: dict[str, Any]) -> list[str]:
    conn = _db(input)
    try:
        path = req_str(input, "filePath")
        direction = opt_str(input, "direction") or "outgoing"
        depth = _opt_uint(input, "maxDepth")
        graph = _load_graph(conn)
        source_id = _file_id(conn, path)
        ids = _walk(graph, source_id, direction != "incoming", depth)
        results = set(_paths(graph, ids))
        if direction != "incoming" and (depth is None or depth > 0):
            results.update(
                _relative_import_targets(conn, source_id, input.get("repoRoot"))
            )
        return sorted(results)
    finally:
        conn.close()


def _relative_import_targets(
    conn: sqlite3.Connection, source_id: int, repo_root: object
) -> list[str]:
    if not isinstance(repo_root, str):
        return []

    from varde_code.index.resolve.core import _FileIndex, _match_import

    root = Path(repo_root).resolve()
    rows = conn.execute("SELECT id,path FROM files ORDER BY id").fetchall()
    positions = {row[0]: index for index, row in enumerate(rows)}
    relative_paths = []
    for _, value in rows:
        path = Path(value)
        if path.is_absolute():
            try:
                path = path.resolve().relative_to(root)
            except ValueError:
                relative_paths.append(value)
                continue
        relative_paths.append(path.as_posix())
    file_index = _FileIndex(relative_paths)

    source_position = positions.get(source_id)
    if source_position is None:
        return []
    imports = conn.execute(
        "SELECT name FROM entities WHERE file_id=? AND kind=? ORDER BY id",
        (source_id, EntityKind.IMPORT.value),
    )
    targets = set()
    for (name,) in imports:
        if not name.startswith("."):
            continue
        target_position = _match_import(name, source_position, file_index)
        if target_position is not None:
            targets.add(rows[target_position][1])
    return sorted(targets)


def dependents(input: dict[str, Any]) -> list[str]:
    return _graph_query(input, reverse=True)


def blast_radius(input: dict[str, Any]) -> list[str]:
    return _graph_query(input, reverse=True)


def _graph_query(input: dict[str, Any], *, reverse: bool) -> list[str]:
    conn = _db(input)
    try:
        graph = _load_graph(conn)
        file_id = _file_id(conn, req_str(input, "filePath"))
        return _paths(
            graph, _walk(graph, file_id, not reverse, _opt_uint(input, "maxDepth"))
        )
    finally:
        conn.close()


def _entity(row: sqlite3.Row) -> dict[str, Any]:
    kind = EntityKind.from_i64(row[0])
    return {
        "name": row[1],
        "kind": kind.as_str() if kind is not None else "unknown",
        "file": row[10],
        "file_id": row[2],
        "span": {
            "start_byte": row[3],
            "end_byte": row[4],
            "start_line": row[5],
            "start_col": row[6],
            "end_line": row[7],
            "end_col": row[8],
        },
        "enclosing_function": row[9],
    }


_ENTITY_COLUMNS = (
    "e.kind,e.name,e.file_id,e.start_byte,e.end_byte,e.start_line,e.start_col,"
    "e.end_line,e.end_col,e.enclosing_function,f.path"
)


def _inheritance(
    conn: sqlite3.Connection, seed: str, language: str | None, up: bool
) -> list[dict[str, Any]]:
    match_col, read_col = (
        ("enclosing_function", "name") if up else ("name", "enclosing_function")
    )
    sql = (
        f"SELECT DISTINCT e.{read_col},f.path FROM entities e JOIN files f "  # noqa: S608 - Column names come from a fixed internal pair.
        f"ON f.id=e.file_id WHERE e.kind IN (15,16) AND e.{match_col}=? "
        f"AND e.{read_col} IS NOT NULL AND e.{read_col}<>''"
    )
    seen = {seed}
    queue = deque([seed])
    result = []
    while queue:
        current = queue.popleft()
        neighbors = []
        for name, path in conn.execute(sql, (current,)):
            if language is None or language_for_path(path) == language:
                neighbors.append(name)
        for name in neighbors:
            if name in seen:
                continue
            seen.add(name)
            row = conn.execute(
                f"SELECT {_ENTITY_COLUMNS} FROM entities e JOIN files f "  # noqa: S608 - Fixed SQL columns.
                f"ON f.id=e.file_id WHERE e.name=? AND e.kind IN (1,2) "
                "ORDER BY e.id",
                (name,),
            ).fetchall()
            decl = next(
                (
                    item
                    for item in row
                    if language is None or language_for_path(item[10]) == language
                ),
                None,
            )
            result.append(_entity(decl) if decl else {"name": name, "kind": "unknown"})
            queue.append(name)
    return result


def type_hierarchy(input: dict[str, Any]) -> dict[str, Any]:
    conn = _db(input)
    try:
        name = req_str(input, "name")
        file_path = opt_str(input, "filePath")
        rows = conn.execute(
            f"SELECT {_ENTITY_COLUMNS} FROM entities e JOIN files f "  # noqa: S608 - Fixed SQL columns.
            f"ON f.id=e.file_id WHERE e.name=? ORDER BY e.id",
            (name,),
        ).fetchall()
        rows = [
            row
            for row in rows
            if file_path is None or _matches_path(row[10], file_path)
        ]
        if not rows:
            raise QueryError("not_found", f"type {name!r}")
        seed = next(
            (
                row
                for row in rows
                if row[0] in (EntityKind.CLASS.value, EntityKind.INTERFACE.value)
            ),
            rows[0],
        )
        lang = language_for_path(seed[10])
        supers = _inheritance(conn, seed[1], lang, True)
        subs = _inheritance(conn, seed[1], lang, False)
        symbol = _entity(seed)
        return {
            "symbol": symbol,
            "supertypes": supers,
            "subtypes": subs,
            "hierarchy": [*reversed(supers), symbol],
        }
    finally:
        conn.close()


def _resolve_seeds(conn: sqlite3.Connection, seed: str) -> tuple[list[int], str]:
    try:
        return [_file_id(conn, seed)], "file"
    except QueryError:
        pass
    exact = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT file_id FROM symbols WHERE name=?", (seed,)
        )
    ]
    if exact:
        return exact, "symbol_exact"
    partial = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT file_id FROM symbols "
            "WHERE lower(name) LIKE '%' || lower(?) || '%'",
            (seed,),
        )
    ]
    if partial:
        return partial, "symbol_partial"
    raise QueryError("not_found", f"no file or symbol matching {seed!r}")


def explore(input: dict[str, Any]) -> dict[str, Any]:
    conn = _db(input)
    try:
        query = input.get("query")
        if not isinstance(query, dict):
            raise QueryError("invalid_input", "query.params.input is required")
        params = query.get("params", query)
        if not isinstance(params, dict) or not isinstance(params.get("input"), str):
            raise QueryError("invalid_input", "query.params.input is required")
        seed = params["input"]
        direction = (
            params.get("direction")
            if isinstance(params.get("direction"), str)
            else "outgoing"
        )
        maximum = _opt_uint(params, "maxItems")
        graph = _load_graph(conn)
        seed_ids, via = _resolve_seeds(conn, seed)
        reached: set[int] = set()
        for file_id in seed_ids:
            if direction == "incoming":
                reached.update(_walk(graph, file_id, False))
            elif direction == "both":
                reached.update(_walk(graph, file_id, True))
                reached.update(_walk(graph, file_id, False))
            else:
                reached.update(_walk(graph, file_id, True))
        reached.difference_update(seed_ids)
        root = Path(req_str(input, "repoRoot"))
        paths = [
            _relative_or_original(path, root) for path in _paths(graph, sorted(reached))
        ]
        if maximum is not None:
            paths = paths[:maximum]
        return {
            "input": seed,
            "resolvedVia": via,
            "seedFiles": [
                _relative_or_original(path, root) for path in _paths(graph, seed_ids)
            ],
            "reachable": paths,
        }
    finally:
        conn.close()


for _name, _handler in (
    ("dependencies", dependencies),
    ("dependents", dependents),
    ("blast_radius", blast_radius),
    ("symbol_blast_radius", symbol_blast_radius),
    ("type_hierarchy", type_hierarchy),
    ("explore", explore),
):
    register_mode(_name, _handler)


__all__ = [
    "Graph",
    "blast_radius",
    "dependencies",
    "dependents",
    "explore",
    "symbol_blast_radius",
    "type_hierarchy",
]
