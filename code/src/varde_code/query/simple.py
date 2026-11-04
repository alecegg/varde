"""Simple SQLite backed code query modes."""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Any, Never

from varde_code.model import EntityKind, SymbolKind

from .freshness import source_root_mismatch
from .modes import register_mode
from .params import QueryError, req_str

_DECLARATIONS = (
    EntityKind.FUNCTION,
    EntityKind.CLASS,
    EntityKind.INTERFACE,
    EntityKind.VARIABLE,
    EntityKind.PARAMETER,
)
_GENERIC_NAMES = {
    "SKILL.md",
    "FLOW.md",
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "main.rs",
    "lib.rs",
    "mod.rs",
    "__init__.py",
    "plan.md",
}


def _db(input: dict[str, Any]) -> sqlite3.Connection:
    path_value = input.get("dbPath")
    if not isinstance(path_value, str):
        from .modes import index_service

        root_value = input.get("repoRoot")
        service = index_service()
        if not isinstance(root_value, str) or service is None:
            raise QueryError("invalid_input", 'missing string field "dbPath"')
        path_value = str(service.repo_db_path(Path(root_value)))
    path = path_value
    if not Path(path).is_file():
        raise QueryError(
            "index_missing",
            (
                f"index missing at {path}; build it with `varde map build` "
                "or read the committed repo-map packs under docs/repo-map/; "
                "find_pattern needs no index"
            ),
        )
    try:
        conn = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        raise QueryError("db_error", str(exc)) from exc
    else:
        return conn


def _raise_stale_index() -> Never:
    raise QueryError(
        "index_stale",
        (
            "dbPath index was built for another source root or predates "
            "source-root validation"
        ),
    )


def _kind(enum: Any, value: int) -> str:
    try:
        return enum(value).as_str()
    except ValueError:
        return "unknown"


def _file_id(conn: sqlite3.Connection, query: str) -> int:
    row = conn.execute("SELECT id FROM files WHERE path = ?", (query,)).fetchone()
    if row is None:
        row = conn.execute(
            """SELECT id FROM files
            WHERE substr(path, -length(?) - 1) = '/' || ?
               OR substr(path, -length(?) - 1) = char(92) || ?
            ORDER BY path LIMIT 1""",
            (query, query, query, query),
        ).fetchone()
    if row is None:
        raise QueryError("not_found", f"file {query!r}")
    return row[0]


def _symbol(row: sqlite3.Row, kind: str, source: bytes | None = None) -> dict[str, Any]:
    result = {
        "kind": kind,
        "name": row[1],
        "file": row[2],
        "span": {
            "start_byte": row[3],
            "end_byte": row[4],
            "start_line": row[5],
            "start_col": row[6],
            "end_line": row[7],
            "end_col": row[8],
        },
    }
    if source is not None:
        try:
            body = source[row[3] : row[4]].decode("utf-8")
            result["body"] = body
        except IndexError, UnicodeDecodeError:
            pass
    return result


def _file_symbols(
    conn: sqlite3.Connection, fid: int, input: dict[str, Any]
) -> list[dict[str, Any]]:
    declarations = conn.execute(
        """SELECT e.kind,e.name,f.path,e.start_byte,e.end_byte,
        e.start_line,e.start_col,e.end_line,e.end_col FROM entities e JOIN files f
        ON f.id=e.file_id
        WHERE e.file_id=? AND e.kind IN (?,?,?,?,?) ORDER BY e.id""",
        (fid, *(kind.value for kind in _DECLARATIONS)),
    ).fetchall()
    ref_clause = "" if input.get("includeReferences") is True else " AND s.kind != ?"
    params: tuple[Any, ...] = (
        (fid,) if not ref_clause else (fid, SymbolKind.REFERENCE.value)
    )
    symbols = conn.execute(
        f"SELECT s.kind,s.name,f.path,s.start_byte,s.end_byte, "  # noqa: S608 - Predicate fragment is selected from fixed internal strings.
        f"s.start_line,s.start_col,s.end_line,s.end_col FROM symbols s "
        f"JOIN files f ON f.id=s.file_id WHERE s.file_id=?{ref_clause} "
        "ORDER BY s.id",
        params,
    ).fetchall()
    rows = [(r, _kind(EntityKind, r[0])) for r in declarations]
    rows.extend((r, _kind(SymbolKind, r[0])) for r in symbols)
    source = None
    if input.get("includeBody") is True and rows:
        root = Path(input.get("repoRoot") or Path(input["dbPath"]).parent)
        with contextlib.suppress(OSError):
            source = (root / rows[0][0][2]).read_bytes()
    return [_symbol(row, kind, source) for row, kind in rows]


def symbols_in_file(input: dict[str, Any]) -> list[dict[str, Any]]:
    file_path = req_str(input, "filePath")
    conn = _db(input)
    try:
        return _file_symbols(conn, _file_id(conn, file_path), input)
    finally:
        conn.close()


def symbols_in_files(input: dict[str, Any]) -> dict[str, Any]:
    paths = input.get("filePaths")
    if not isinstance(paths, list):
        raise QueryError("invalid_input", 'missing array field "filePaths"')
    if any(not isinstance(path, str) for path in paths):
        raise QueryError("invalid_input", "filePaths entries must be strings")
    conn = _db(input)
    try:
        results = {}
        for path in paths:
            try:
                repo_root = req_str(input, "repoRoot")
                if source_root_mismatch(req_str(input, "dbPath"), repo_root):
                    _raise_stale_index()
                results[path] = _file_symbols(conn, _file_id(conn, path), input)
            except QueryError as exc:
                results[path] = {"error": {"code": exc.code, "message": exc.message}}
        return results
    finally:
        conn.close()


def get_symbol(input: dict[str, Any]) -> dict[str, Any]:
    conn = _db(input)
    try:
        name, kind, file_path = (
            req_str(input, "name"),
            input.get("kind"),
            input.get("filePath"),
        )
        sources = []
        entity_by_name = {e.as_str(): e for e in _DECLARATIONS}
        if kind is None or kind in {e.as_str() for e in _DECLARATIONS}:
            entity_kind = entity_by_name.get(kind) if isinstance(kind, str) else None
            where = (
                " AND e.kind=?"
                if entity_kind is not None
                else " AND e.kind IN (?,?,?,?,?)"
            )
            args = (
                (name, entity_kind.value)
                if entity_kind is not None
                else (
                    name,
                    *(e.value for e in _DECLARATIONS),
                )
            )
            sources.extend(
                (r, _kind(EntityKind, r[0]), 0)
                for r in conn.execute(
                    (
                        f"SELECT e.kind,e.name,f.path,e.start_byte,e.end_byte,"  # noqa: S608 - Predicate is fixed internally; values are bound separately.
                        "e.start_line,e.start_col,e.end_line,e.end_col "
                        "FROM entities e JOIN files f ON f.id=e.file_id "
                        f"WHERE e.name=?{where} ORDER BY CASE e.kind "
                        "WHEN 1 THEN 0 WHEN 2 THEN 0 WHEN 0 THEN 1 "
                        "WHEN 3 THEN 2 WHEN 4 THEN 3 ELSE 4 END,e.id"
                    ),
                    args,
                )
            )
        if kind is None or kind in {"binding", "reference"}:
            symbol_by_name = {e.as_str(): e for e in SymbolKind}
            symbol_kind = symbol_by_name.get(kind) if isinstance(kind, str) else None
            where = " AND s.kind=?" if symbol_kind is not None else ""
            args = (name, symbol_kind.value) if symbol_kind is not None else (name,)
            sources.extend(
                (r, _kind(SymbolKind, r[0]), 1)
                for r in conn.execute(
                    (
                        f"SELECT s.kind,s.name,f.path,s.start_byte,s.end_byte,"  # noqa: S608 - Predicate is fixed internally; values are bound separately.
                        "s.start_line,s.start_col,s.end_line,s.end_col "
                        "FROM symbols s JOIN files f ON f.id=s.file_id "
                        f"WHERE s.name=?{where} ORDER BY CASE s.kind "
                        "WHEN 0 THEN 0 ELSE 1 END,s.id"
                    ),
                    args,
                )
            )
        if isinstance(file_path, str):
            sources = [item for item in sources if _matches_path(item[0][2], file_path)]
        if not sources:
            raise QueryError("not_found", f"symbol {name!r}")
        row, rendered, _ = sources[0]
        source = None
        if input.get("includeBody") is True:
            with contextlib.suppress(OSError):
                source = (Path(req_str(input, "repoRoot")) / row[2]).read_bytes()
        return _symbol(row, rendered, source)
    finally:
        conn.close()


def _matches_path(path: str, query: str) -> bool:
    return path == query or path.endswith(("/" + query, "\\" + query))


def tests_for_file(input: dict[str, Any]) -> list[str]:
    conn = _db(input)
    try:
        target = _file_id(conn, req_str(input, "filePath"))
        repo_root = Path(req_str(input, "repoRoot"))
        candidates = conn.execute(
            "SELECT id,path FROM files WHERE is_test_path=1"
        ).fetchall()
        importers: dict[int, list[int]] = {}
        for row in conn.execute(
            "SELECT from_file_id,to_file_id FROM resolved_edges "
            "WHERE kind=1 AND resolved=1 AND to_file_id IS NOT NULL"
        ):
            importers.setdefault(row[1], []).append(row[0])
        reach, stack = set(), [target]
        while stack:
            for parent in importers.get(stack.pop(), ()):
                if parent not in reach:
                    reach.add(parent)
                    stack.append(parent)
        graph = sorted(path for fid, path in candidates if fid in reach)
        if graph:
            return graph
        target_path = (
            conn.execute("SELECT path FROM files WHERE id=?", (target,))
            .fetchone()[0]
            .replace("\\", "/")
        )
        root_text = str(repo_root).replace("\\", "/").rstrip("/")
        if target_path.startswith(root_text + "/"):
            target_path = target_path[len(root_text) + 1 :]
        name = target_path.rsplit("/", 1)[-1]
        if name in _GENERIC_NAMES or (name.startswith("index.") and len(name) > 6):
            parent = target_path.rsplit("/", 1)[0] if "/" in target_path else ""
            needle = (parent.rsplit("/", 1)[-1] + "/" if parent else "") + name
        else:
            needle = name
        needles = {target_path, needle}
        hits = []
        for _, path in candidates:
            try:
                text = (repo_root / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if any(_has_path_name(text, n) for n in needles):
                hits.append(path)
        return sorted(hits)
    finally:
        conn.close()


def _has_path_name(text: str, needle: str) -> bool:
    if not needle:
        return False
    start = 0
    while (index := text.find(needle, start)) >= 0:
        if index == 0 or not (
            text[index - 1].isascii()
            and (text[index - 1].isalnum() or text[index - 1] in "._-")
        ):
            return True
        start = index + 1
    return False


def find_imports(input: dict[str, Any]) -> list[dict[str, Any]]:
    conn = _db(input)
    try:
        fid = _file_id(conn, req_str(input, "filePath"))
        rows = conn.execute(
            """SELECT e.to_file_id,e.resolved,f.path FROM resolved_edges e
            LEFT JOIN files f ON f.id=e.to_file_id
            WHERE e.kind=1 AND e.from_file_id=? ORDER BY e.id""",
            (fid,),
        )
        return [
            {"to": row[2] or "", "resolved": row[1] == 1, "to_file_id": row[0]}
            for row in rows
        ]
    finally:
        conn.close()


def filter_symbols(input: dict[str, Any]) -> list[dict[str, Any]]:
    conn = _db(input)
    try:
        kind, file, language = (
            input.get("kind"),
            input.get("file"),
            input.get("language"),
        )
        file_id = _file_id(conn, file) if isinstance(file, str) else None
        entity_kinds = {item.as_str(): item.value for item in _DECLARATIONS}
        symbol_kinds = {item.as_str(): item.value for item in SymbolKind}
        want_entities = kind is None or kind in entity_kinds
        want_symbols = kind is None or kind in symbol_kinds
        if kind is not None and not (want_entities or want_symbols):
            return []
        out = []
        for table, enum, selected_kind, default_kinds in (
            (
                "entities",
                EntityKind,
                entity_kinds.get(kind) if isinstance(kind, str) else None,
                tuple(entity_kinds.values()),
            ),
            (
                "symbols",
                SymbolKind,
                symbol_kinds.get(kind) if isinstance(kind, str) else None,
                (),
            ),
        ):
            if (table == "entities" and not want_entities) or (
                table == "symbols" and not want_symbols
            ):
                continue
            clauses, params = [], []
            if selected_kind is not None:
                clauses.append("t.kind=?")
                params.append(selected_kind)
            elif default_kinds:
                clauses.append(
                    "t.kind IN (" + ",".join("?" for _ in default_kinds) + ")"
                )
                params.extend(default_kinds)
            if file_id is not None:
                clauses.append("t.file_id=?")
                params.append(file_id)
            if isinstance(input.get("minCyclomaticComplexity"), int) and not isinstance(
                input.get("minCyclomaticComplexity"), bool
            ):
                clauses.append("COALESCE(f.complexity,0)>=?")
                params.append(input["minCyclomaticComplexity"])
            where = " AND ".join(clauses) or "1=1"
            rows = conn.execute(
                f"SELECT t.kind,t.name,f.path,t.start_byte,t.end_byte, "  # noqa: S608 - Table and predicates come from fixed internal allowlists.
                f"t.start_line,t.start_col,t.end_line,t.end_col FROM {table} t "
                f"JOIN files f ON f.id=t.file_id WHERE {where} ORDER BY t.id",
                params,
            )
            for row in rows:
                path = row[2]
                if isinstance(language, str):
                    suffix = Path(path).suffix.lower()
                    aliases = {
                        "ts": "typescript",
                        "tsx": "tsx",
                        "js": "javascript",
                        "py": "python",
                        "rs": "rust",
                        "go": "go",
                        "java": "java",
                        "c": "c",
                        "h": "c",
                        "cpp": "cpp",
                        "cc": "cpp",
                        "rb": "ruby",
                        "php": "php",
                        "swift": "swift",
                        "kt": "kotlin",
                        "scala": "scala",
                        "dart": "dart",
                        "lua": "lua",
                        "ex": "elixir",
                        "hs": "haskell",
                        "sh": "bash",
                    }
                    actual = aliases.get(
                        suffix.removeprefix("."), suffix.removeprefix(".")
                    )
                    accepted = {
                        "ts": "typescript",
                        "js": "javascript",
                        "py": "python",
                        "c++": "cpp",
                        "golang": "go",
                        "cs": "csharp",
                        "kt": "kotlin",
                        "rb": "ruby",
                        "ex": "elixir",
                        "hs": "haskell",
                        "sh": "bash",
                    }.get(language.lower(), language.lower())
                    if actual != accepted and not (
                        accepted == "typescript" and actual == "tsx"
                    ):
                        continue
                out.append(_symbol(row, _kind(enum, row[0])))
        paged = any(
            key in input for key in ("resultsLimit", "resultsOffset", "fullResults")
        )
        cap = input.get("maxSymbols") if not paged else None
        return (
            out[:cap]
            if isinstance(cap, int) and not isinstance(cap, bool) and cap >= 0
            else out
        )
    finally:
        conn.close()


for _name, _handler in (
    ("symbols_in_file", symbols_in_file),
    ("symbols_in_files", symbols_in_files),
    ("get_symbol", get_symbol),
    ("tests_for_file", tests_for_file),
    ("find_imports", find_imports),
    ("filter_symbols", filter_symbols),
):
    register_mode(_name, _handler)
