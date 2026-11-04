"""File mapping, change, hotspot, cluster, and context query modes."""

from __future__ import annotations

import sqlite3
from collections import deque
from pathlib import Path
from typing import Any

from varde_code.index.lexical import lexical_search
from varde_code.model import EntityKind, SymbolKind

from .foundational_files import leaderboard as foundational_leaderboard
from .fusion import fuse_rankings, rerank_files
from .modes import register_mode
from .noise_filter import is_generated_or_vendored_path, is_non_source_path
from .params import QueryError, nonnegative_int, opt_str, req_str
from .simple import _db, _file_id

_FUSION_LEXICAL_LIMIT = 30
_FALLBACK_MIN_SEEDS = 3


def _symbol_kind(value: int) -> str:
    kind = SymbolKind.from_i64(value)
    return kind.as_str() if kind is not None else "unknown"


def _entity_kind(value: int) -> str:
    kind = EntityKind.from_i64(value)
    return kind.as_str() if kind is not None else "unknown"


def map_file(input: dict[str, Any]) -> dict[str, Any]:
    conn = _db(input)
    try:
        fid = _file_id(conn, req_str(input, "filePath"))
        row = conn.execute(
            "SELECT path,complexity,churn,fan_in,fan_out,community_id "
            "FROM files WHERE id=?",
            (fid,),
        ).fetchone()
        fan_in = conn.execute(
            "SELECT COUNT(DISTINCT from_file_id) FROM resolved_edges "
            "WHERE resolved=1 AND to_file_id=? AND from_file_id!=to_file_id",
            (fid,),
        ).fetchone()[0]
        fan_out = conn.execute(
            "SELECT COUNT(DISTINCT to_file_id) FROM resolved_edges "
            "WHERE resolved=1 AND from_file_id=? AND to_file_id IS NOT NULL "
            "AND from_file_id!=to_file_id",
            (fid,),
        ).fetchone()[0]
        label = (
            conn.execute(
                "SELECT label FROM communities WHERE id=?", (row[5],)
            ).fetchone()
            if row[5] is not None
            else None
        )
        return {
            "path": row[0],
            "complexity": row[1],
            "churn": row[2],
            "fan_in": row[3],
            "fan_out": row[4],
            "fan_in_files": fan_in,
            "fan_out_files": fan_out,
            "community_id": row[5],
            "community_label": label[0] if label else None,
        }
    finally:
        conn.close()


def map_symbol(input: dict[str, Any]) -> dict[str, Any]:
    conn = _db(input)
    try:
        name = req_str(input, "name")
        sql = """SELECT e.kind,e.name,e.file_id,e.start_byte,e.end_byte,e.start_line,
            e.start_col,e.end_line,e.end_col,e.enclosing_function,e.method,e.path,
            e.status,e.body_shape,f.path FROM entities e
            JOIN files f ON f.id=e.file_id WHERE e.name=? ORDER BY e.id"""
        for row in conn.execute(sql, (name,)):
            if opt_str(input, "sourceFile") and not _matches_path(
                row[14], input["sourceFile"]
            ):
                continue
            kind = EntityKind.from_i64(row[0])
            return {
                "name": row[1],
                "kind": kind.as_str() if kind is not None else "unknown",
                "file": row[14],
                "file_id": row[2],
                "span": dict(
                    zip(
                        (
                            "start_byte",
                            "end_byte",
                            "start_line",
                            "start_col",
                            "end_line",
                            "end_col",
                        ),
                        row[3:9],
                        strict=False,
                    )
                ),
                "enclosing_function": row[9],
                "method": row[10],
                "path": row[11],
                "status": row[12],
                "body_shape": row[13],
            }
        raise QueryError("not_found", f"symbol {name!r}")
    finally:
        conn.close()


def _matches_path(path: str, query: str) -> bool:
    return path == query or path.endswith(("/" + query, "\\" + query))


def map_path(input: dict[str, Any]) -> list[str]:
    conn = _db(input)
    try:
        source, target = (
            _file_id(conn, req_str(input, "sourceFile")),
            _file_id(conn, req_str(input, "targetFile")),
        )
        paths = {row[0]: row[1] for row in conn.execute("SELECT id,path FROM files")}
        adjacency: dict[int, list[int]] = {}
        for a, b in conn.execute(
            "SELECT from_file_id,to_file_id FROM resolved_edges "
            "WHERE resolved=1 AND to_file_id IS NOT NULL"
        ):
            adjacency.setdefault(a, []).append(b)
        queue = deque([source])
        parent: dict[int, int | None] = {source: None}
        maximum = nonnegative_int(input, "maxDepth")
        depth = {source: 0}
        while queue:
            current = queue.popleft()
            if current == target:
                break
            if maximum is not None and depth[current] >= maximum:
                continue
            for child in adjacency.get(current, ()):
                if child not in parent:
                    parent[child] = current
                    depth[child] = depth[current] + 1
                    queue.append(child)
        if target not in parent:
            return []
        ids = []
        current: int | None = target
        while current is not None:
            ids.append(current)
            current = parent[current]
        return [paths[i] for i in reversed(ids) if i in paths]
    finally:
        conn.close()


def detect_changes(input: dict[str, Any]) -> list[dict[str, Any]]:
    root_value = opt_str(input, "repoRoot")
    if not root_value:
        raise QueryError(
            "invalid_input",
            "detect_changes needs repoRoot (or a dbPath inside a git repo)",
        )
    root = Path(root_value)
    mode = opt_str(input, "diffMode") or "working_tree"
    args = (
        ["diff", "--cached", "--name-status"]
        if mode == "staged"
        else [
            "diff",
            "--name-status",
            *([req_str(input, "range")] if mode == "range" else []),
        ]
    )
    import subprocess

    try:
        result = subprocess.run(  # noqa: S603 - Runs git with constructed repository arguments.
            ["git", *args],  # noqa: S607 - Uses the system git executable from PATH.
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    conn = _db(input)
    try:
        out = []
        for line in result.stdout.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            status, rel = parts
            fid = conn.execute(
                "SELECT id FROM files WHERE path=? OR path LIKE ? "
                "ORDER BY path LIMIT 1",
                (str(root / rel), "%/" + rel),
            ).fetchone()
            persisted = (
                []
                if fid is None
                else [
                    (
                        r[0],
                        _symbol_kind(r[1]),
                        r[2],
                        r[3],
                    )
                    for r in conn.execute(
                        "SELECT name,kind,start_byte,end_byte FROM symbols "
                        "WHERE file_id=?",
                        (fid[0],),
                    )
                ]
            )
            # Source extraction signatures are intentionally limited to
            # supported parsed languages.
            current = []
            try:
                from varde_code.extract import extract_symbols
                from varde_code.parse import parse_file

                parsed = parse_file(root / rel)
                if parsed:
                    current = [
                        (s.name, s.kind.as_str(), s.span.start_byte, s.span.end_byte)
                        for s in extract_symbols(parsed.root)
                    ]
            except ImportError, OSError, ValueError, TypeError:
                pass
            persisted_names = {s[0] for s in persisted}
            current_names = {s[0] for s in current}
            changes = []
            changes.extend(
                {"name": n, "kind": k, "change": "added"}
                for n, k, *_ in current
                if n not in persisted_names
            )
            changes.extend(
                {"name": n, "kind": k, "change": "removed"}
                for n, k, *_ in persisted
                if n not in current_names
            )
            by_name = {n: (sb, eb) for n, _k, sb, eb in persisted}
            changes.extend(
                {"name": n, "kind": k, "change": "modified"}
                for n, k, sb, eb in current
                if n in by_name and by_name[n] != (sb, eb)
            )
            out.append(
                {
                    "file": rel,
                    "status": status,
                    "symbols": sorted(changes, key=lambda item: item["name"]),
                }
            )
        return out
    finally:
        conn.close()


def hotspots_on(
    conn: sqlite3.Connection, limit: int | None = None
) -> list[dict[str, Any]]:
    files = [
        (p, c or 0, h or 0)
        for p, c, h in conn.execute(
            "SELECT path,complexity,churn FROM files WHERE is_test_path=0"
        )
        if not is_generated_or_vendored_path(p) and not is_non_source_path(p)
    ]
    varies = len({churn for _, _, churn in files}) > 1
    rows = [(p, c, h, c * h if varies else c) for p, c, h in files]
    rows.sort(key=lambda row: (-row[3], row[0]))
    if limit is not None:
        rows = rows[:limit]
    return [{"file": p, "complexity": c, "churn": h, "score": s} for p, c, h, s in rows]


def hotspots(input: dict[str, Any]) -> list[dict[str, Any]]:
    conn = _db(input)
    try:
        return hotspots_on(conn)
    finally:
        conn.close()


def foundational_files(input: dict[str, Any]) -> list[dict[str, Any]]:
    conn = _db(input)
    try:
        return foundational_leaderboard(conn)
    finally:
        conn.close()


def clusters(input: dict[str, Any]) -> dict[str, Any]:
    conn = _db(input)
    try:
        member_rows = conn.execute(
            "SELECT cm.community_id,f.id,f.path FROM community_members cm "
            "JOIN files f ON f.id=cm.file_id"
        ).fetchall()
        by_file = {fid: cid for cid, fid, _path in member_rows}
        members: dict[int, list[tuple[int, str]]] = {}
        for cid, fid, path in member_rows:
            members.setdefault(cid, []).append((fid, path))
        internal: dict[int, int] = {}
        external: dict[int, int] = {}
        for a, b in conn.execute(
            "SELECT from_file_id,to_file_id FROM resolved_edges "
            "WHERE resolved=1 AND to_file_id IS NOT NULL"
        ):
            left, right = by_file.get(a), by_file.get(b)
            if left is None or right is None:
                continue
            bucket = internal if left == right else external
            bucket[left] = bucket.get(left, 0) + 1
            if left != right:
                external[right] = external.get(right, 0) + 1

        def render(cid: int) -> dict[str, Any]:
            inside, outside = internal.get(cid, 0), external.get(cid, 0)
            return {
                "id": cid,
                "files": sorted(path for _, path in members[cid]),
                "label": None,
                "cohesion": inside / (inside + outside) if inside + outside else 0.0,
            }

        seed = opt_str(input, "seedPath")
        if seed:
            fid = _file_id(conn, seed)
            cid = by_file.get(fid)
            return {"clusters": [render(cid)] if cid is not None else []}
        minimum = nonnegative_int(input, "minSize", 2) or 2
        maximum = nonnegative_int(input, "maxClusters")
        cohesion = input.get("minCohesion", 0.0)
        result = [
            render(cid)
            for cid, files in members.items()
            if len(files) >= minimum and render(cid)["cohesion"] >= cohesion
        ]
        result.sort(key=lambda item: (-item["cohesion"], -len(item["files"])))
        if maximum is not None:
            result = result[:maximum]
        return {"clusters": result}
    finally:
        conn.close()


def context_pack(input: dict[str, Any]) -> dict[str, Any]:
    query = req_str(input, "query")
    repo_root = Path(req_str(input, "repoRoot"))
    ranking_mode = input.get("rankingMode", "fallback")
    if ranking_mode not in {"structural", "fallback"}:
        raise QueryError(
            "invalid_input",
            "rankingMode must be 'structural' or 'fallback'",
        )
    tokens = query.split() or [query]
    conn = _db(input)
    try:
        files = conn.execute(
            "SELECT id,path,complexity,churn FROM files ORDER BY path"
        ).fetchall()
        symbols = _context_symbols(conn, tokens)
        seed_ids = _context_file_matches(conn, tokens)
        seed_ids.update(row[3] for row in symbols)
        seed_order = None
        should_fuse = ranking_mode == "fallback" and len(seed_ids) < _FALLBACK_MIN_SEEDS
        if should_fuse:
            symbols, seed_order = _fused_context_candidates(
                conn, query, tokens, files, symbols, seed_ids
            )
            seed_ids = set(seed_order)
        if not seed_ids:
            raise QueryError("not_found", f"no files or symbols matching {query!r}")
        graph: dict[int, set[int]] = {}
        for a, b in conn.execute(
            "SELECT from_file_id,to_file_id FROM resolved_edges "
            "WHERE resolved=1 AND to_file_id IS NOT NULL"
        ):
            graph.setdefault(a, set()).add(b)
            graph.setdefault(b, set()).add(a)
        neighbor_ids: set[int] = set()
        for fid in seed_ids:
            neighbor_ids.update(graph.get(fid, ()))
        neighbor_ids.difference_update(seed_ids)
        byid = {row[0]: row for row in files}
        topicality = _context_topicality(conn, tokens, symbols)
        seeds = _ordered_context_seeds(seed_order, seed_ids, byid, topicality)
        neighbors = sorted(
            (byid[fid] for fid in neighbor_ids if fid in byid),
            key=lambda row: (-((row[2] or 0) + (row[3] or 0)), row[1]),
        )
        ordered = [*seeds, *neighbors]
        file_items = [
            {"path": row[1], "relevance": "seed" if row[0] in seed_ids else "neighbor"}
            for row in ordered
        ]
        selected = [r[0] for r in ordered]
        sym_items = []
        for _id, name, kind, fid, start, end, path in symbols:
            if fid not in selected or not (
                input.get("includeOccurrences") is True or kind in (0, 1, 2, 3, 5, 13)
            ):
                continue
            sym_items.append(
                {
                    "name": name,
                    "filePath": path,
                    "kind": _entity_kind(kind),
                    "span": {"start_line": start, "end_line": end},
                }
            )
        reading = [
            Path(r[1]).resolve().relative_to(repo_root.resolve()).as_posix()
            for r in ordered
        ]
        tests = []
        for fid in sorted(seed_ids):
            path = byid.get(fid, (None, ""))[1]
            # Coverage uses direct resolved import reachability, matching the
            # graph-first tests heuristic.
            for test_id, test_path in conn.execute(
                "SELECT id,path FROM files WHERE is_test_path=1"
            ):
                if test_id in graph.get(fid, set()):
                    tests.append({"path": test_path, "coversFile": path})
        return {
            "files": file_items,
            "symbols": sym_items,
            "tests": tests,
            "readingOrder": reading,
        }
    finally:
        conn.close()


def _ordered_context_seeds(
    seed_order: list[int] | None,
    seed_ids: set[int],
    byid: dict[int, sqlite3.Row],
    topicality: dict[int, tuple[bool, int]],
) -> list[sqlite3.Row]:
    if seed_order is not None:
        return [byid[fid] for fid in seed_order if fid in byid]
    return sorted(
        (byid[fid] for fid in seed_ids if fid in byid),
        key=lambda row: (*_context_rank(row, topicality), row[1]),
    )


def _context_file_matches(conn: sqlite3.Connection, tokens: list[str]) -> set[int]:
    ids: set[int] = set()
    for token in tokens:
        pattern = f"%{_escape_like(token.lower())}%"
        ids.update(
            row[0]
            for row in conn.execute(
                "SELECT id FROM files WHERE lower(path) LIKE ? ESCAPE '\\'",
                (pattern,),
            )
        )
    return ids


def _fused_context_candidates(
    conn: sqlite3.Connection,
    query: str,
    tokens: list[str],
    files: list[sqlite3.Row],
    symbols: list[tuple[Any, ...]],
    structural_ids: set[int],
) -> tuple[list[tuple[Any, ...]], list[int]]:
    lexical = lexical_search(conn, query, _FUSION_LEXICAL_LIMIT)
    entity_ids = [entity_id for entity_id, _ in lexical]
    entity_files: dict[int, int] = {}
    lexical_symbols: dict[int, tuple[Any, ...]] = {}
    if entity_ids:
        placeholders = ",".join("?" for _ in entity_ids)
        for row in conn.execute(
            f"SELECT e.id,e.name,e.kind,e.file_id,e.start_line,e.end_line,f.path "  # noqa: S608 - Only the generated placeholder count is interpolated.
            f"FROM entities e JOIN files f ON f.id=e.file_id "
            f"WHERE e.id IN ({placeholders})",
            entity_ids,
        ):
            lexical_symbols[row[0]] = tuple(row)
            entity_files[row[0]] = row[3]
    symbols_by_id = {row[0]: row for row in symbols}
    symbols_by_id.update(lexical_symbols)
    symbols = list(symbols_by_id.values())
    byid = {row[0]: row for row in files}
    topicality = _context_topicality(conn, tokens, symbols)
    structural_order = sorted(
        (byid[fid] for fid in structural_ids if fid in byid),
        key=lambda row: (*_context_rank(row, topicality), row[1]),
    )
    scores = fuse_rankings(
        [row[0] for row in structural_order],
        lexical[:_FUSION_LEXICAL_LIMIT],
        entity_files,
    )
    names: dict[int, set[str]] = {}
    for row in symbols:
        names.setdefault(row[3], set()).add(row[1])
    paths = {row[0]: row[1] for row in files}
    return symbols, rerank_files(scores, paths, query, names)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _context_symbol_rank(kind: int) -> int:
    return {0: 0, 1: 0, 2: 0, 13: 0, 5: 1, 3: 2, 4: 3, 6: 5}.get(kind, 4)


def _context_symbols(
    conn: sqlite3.Connection, tokens: list[str]
) -> list[tuple[Any, ...]]:
    sql = """SELECT e.id,e.name,e.kind,e.file_id,e.start_line,e.end_line,f.path
        FROM entities e JOIN files f ON f.id=e.file_id
        WHERE lower(e.name) = lower(?) ORDER BY e.id"""
    fuzzy_sql = """SELECT e.id,e.name,e.kind,e.file_id,e.start_line,e.end_line,f.path
        FROM entities e JOIN files f ON f.id=e.file_id
        WHERE lower(e.name) LIKE ? ESCAPE '\\'
        ORDER BY CASE e.kind WHEN 0 THEN 0 WHEN 1 THEN 0 WHEN 2 THEN 0
            WHEN 13 THEN 0 WHEN 5 THEN 1 WHEN 3 THEN 2 WHEN 4 THEN 3
            WHEN 6 THEN 5 ELSE 4 END, e.id LIMIT 200"""
    found: dict[int, tuple[Any, ...]] = {}
    for token in tokens:
        for row in conn.execute(sql, (token,)):
            found[row[0]] = tuple(row)
        for row in conn.execute(fuzzy_sql, (f"%{_escape_like(token.lower())}%",)):
            found[row[0]] = tuple(row)
    return sorted(
        found.values(),
        key=lambda row: (
            _context_symbol_rank(row[2]),
            not any(row[1].lower() == token.lower() for token in tokens),
            row[1].lower(),
            row[2],
            row[0],
        ),
    )


def _context_topicality(
    conn: sqlite3.Connection, tokens: list[str], symbols: list[tuple[Any, ...]]
) -> dict[int, tuple[bool, int]]:
    scores: dict[int, list[Any]] = {}
    for token in tokens:
        pattern = f"%{_escape_like(token.lower())}%"
        matched: set[int] = set()
        for file_id, path in conn.execute(
            "SELECT id,path FROM files WHERE lower(path) LIKE ? ESCAPE '\\'",
            (pattern,),
        ):
            matched.add(file_id)
            if (
                path.lower() == token.lower()
                or Path(path).name.lower() == token.lower()
            ):
                scores.setdefault(file_id, [False, 0])[0] = True
        for row in conn.execute(
            """SELECT file_id FROM entities WHERE lower(name) LIKE ? ESCAPE '\\'
            ORDER BY CASE kind WHEN 0 THEN 0 WHEN 1 THEN 0 WHEN 2 THEN 0
                WHEN 13 THEN 0 WHEN 5 THEN 1 WHEN 3 THEN 2 WHEN 4 THEN 3
                WHEN 6 THEN 5 ELSE 4 END, id LIMIT 200""",
            (pattern,),
        ):
            matched.add(row[0])
        for file_id in matched:
            scores.setdefault(file_id, [False, 0])[1] += 1
    for _id, name, kind, file_id, *_ in symbols:
        if kind in (0, 1, 2, 3, 5, 13) and any(
            name.lower() == token.lower() for token in tokens
        ):
            scores.setdefault(file_id, [False, 0])[0] = True
    return {file_id: (score[0], score[1]) for file_id, score in scores.items()}


def _context_rank(
    row: sqlite3.Row, topicality: dict[int, tuple[bool, int]]
) -> tuple[bool, int, int]:
    exact, matched = topicality.get(row[0], (False, 0))
    return not exact, -matched, -((row[2] or 0) + (row[3] or 0))


for _name, _handler in (
    ("map_file", map_file),
    ("map_symbol", map_symbol),
    ("map_path", map_path),
    ("detect_changes", detect_changes),
    ("hotspots", hotspots),
    ("clusters", clusters),
    ("context_pack", context_pack),
):
    register_mode(_name, _handler)

__all__ = [
    "clusters",
    "context_pack",
    "detect_changes",
    "foundational_files",
    "hotspots",
    "hotspots_on",
    "map_file",
    "map_path",
    "map_symbol",
]
