"""Entrypoint records and detectors over the persisted code index."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_code.model import EntityKind, RoleTag
from varde_code.parse import language_for_path

from .noise_filter import (
    is_frontend_asset_path,
    is_generated_or_vendored_path,
    is_scaffold_template_path,
)


@dataclass(frozen=True)
class Entrypoint:
    entity_id: int
    file: str
    symbol: str
    role: RoleTag
    flow_root: bool = True
    method: str | None = None
    path: str | None = None

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "entity_id": self.entity_id,
            "file": self.file,
            "symbol": self.symbol,
            "role": self.role.value,
        }
        if self.method is not None:
            result["method"] = self.method
        if self.path is not None:
            result["path"] = self.path
        return result


BOOTSTRAP_FILENAMES = frozenset(
    {
        "main.rs",
        "main.py",
        "__main__.py",
        "Program.cs",
        "index.ts",
        "index.js",
        "main.go",
        "main.java",
        "Main.java",
        "main.c",
        "main.cpp",
    }
)


def is_bootstrap_filename(path: str) -> bool:
    return path.replace("\\", "/").rsplit("/", 1)[-1] in BOOTSTRAP_FILENAMES


def process_main_name_for_path(path: str) -> str | None:
    language = language_for_path(Path(path))
    if language in {"rust", "go", "c", "cpp", "java", "kotlin"}:
        return "main"
    if language == "csharp":
        return "Main"
    return None


def join_route_path(prefix: str | None, sub: str | None) -> str | None:
    segments = [part.strip().strip("/") for part in (prefix, sub) if part is not None]
    segments = [part for part in segments if part]
    return "/" + "/".join(segments) if segments else None


def detect_routes(conn: sqlite3.Connection) -> list[Entrypoint]:
    rows = conn.execute(
        """SELECT e.id, e.file_id, f.path, e.method, e.path, e.owner_type
           FROM entities e JOIN files f ON f.id = e.file_id
           WHERE e.kind = ? AND f.is_test_path = 0""",
        (EntityKind.ROUTE.as_i64(),),
    ).fetchall()
    handlers = _handler_index(conn, [row[5] for row in rows if row[5]])
    results: list[Entrypoint] = []
    seen: set[tuple[str, str]] = set()
    for route_id, file_id, file, method, path, handler in rows:
        if not _call_route_language(file) or _excluded_path(file) or not path:
            continue
        verb = method.upper() if method and method != "*" else None
        symbol = f"{verb} {path}" if verb else path
        key = (file, symbol)
        if key in seen:
            continue
        seen.add(key)
        entity_id = handlers.get((file_id, handler)) or handlers.get((None, handler))
        results.append(
            Entrypoint(
                entity_id if entity_id is not None else route_id,
                file,
                symbol,
                RoleTag.ROUTE_HANDLER,
                entity_id is not None,
                verb,
                path,
            )
        )
    return sorted(results, key=lambda item: (item.file, item.symbol))


def detect_process_mains(conn: sqlite3.Connection) -> list[Entrypoint]:
    rows = conn.execute(
        """SELECT e.id, f.path, e.name FROM entities e
           JOIN files f ON f.id = e.file_id
           WHERE e.kind = ? AND f.is_test_path = 0
             AND e.owner_type IS NULL AND e.name IN ('main', 'Main')""",
        (EntityKind.FUNCTION.as_i64(),),
    ).fetchall()
    results = [
        Entrypoint(entity_id, file, name, RoleTag.PROCESS_MAIN)
        for entity_id, file, name in rows
        if not _excluded_path(file) and process_main_name_for_path(file) == name
    ]
    return sorted(results, key=lambda item: (item.file, item.symbol))


def detect_tagged_entrypoints(conn: sqlite3.Connection) -> list[Entrypoint]:
    try:
        rows = conn.execute(
            """SELECT e.id, f.path, e.name, e.role_tag FROM entities e
               JOIN files f ON f.id=e.file_id
               WHERE e.kind IN (?,?) AND f.is_test_path=0 AND e.role_tag IS NOT NULL
               ORDER BY f.path, e.name""",
            (EntityKind.FUNCTION.as_i64(), EntityKind.CLASS.as_i64()),
        ).fetchall()
    except sqlite3.Error:
        return []
    results = []
    for entity_id, file, name, role in rows:
        if _excluded_path(file) or is_bootstrap_filename(file):
            continue
        try:
            tag = RoleTag(role)
        except ValueError:
            continue
        results.append(Entrypoint(entity_id, file, name, tag))
    return results


def detect_node_entrypoints(
    conn: sqlite3.Connection, repo_root: str | Path | None
) -> list[Entrypoint]:
    if repo_root is None:
        return []
    rows = conn.execute(
        """SELECT e.id, f.path, e.name FROM entities e JOIN files f ON f.id=e.file_id
           WHERE e.kind=? AND f.is_test_path=0 AND e.owner_type IS NULL
             AND e.name IN ('main','handleRequest')""",
        (EntityKind.FUNCTION.as_i64(),),
    ).fetchall()
    root = Path(repo_root)
    results = []
    sources: dict[str, str | None] = {}
    for entity_id, file, name in rows:
        if _excluded_path(file) or language_for_path(Path(file)) not in {
            "typescript",
            "tsx",
            "javascript",
        }:
            continue
        if file not in sources:
            try:
                sources[file] = (root / file).read_text(encoding="utf-8")
            except OSError, UnicodeError:
                sources[file] = None
        source = sources[file]
        if source is None:
            continue
        if name == "main" and _has_node_direct_run_call(source):
            results.append(Entrypoint(entity_id, file, name, RoleTag.PROCESS_MAIN))
        elif name == "handleRequest" and _has_node_http_handler_call(source):
            results.append(Entrypoint(entity_id, file, name, RoleTag.ROUTE_HANDLER))
    return sorted(results, key=lambda item: (item.file, item.symbol))


def _has_node_direct_run_call(source: str) -> bool:
    guards = re.finditer(
        r"if\s*\(([^)]*(?:\)[^)]*)?)\)\s*\{([^{}]*)\}", source, re.DOTALL
    )
    for guard in guards:
        condition, body = guard.groups()
        if (
            condition.lstrip().startswith("!")
            or "!==" in condition
            or "!=" in condition
        ):
            continue
        equals_entry = (
            ("import.meta.url" in condition and "process.argv[1]" in condition)
            or "require.main" in condition
            and "module" in condition
        )
        if equals_entry and re.search(r"\bmain\s*\(", body):
            return True
    return False


def _has_node_http_handler_call(source: str) -> bool:
    return bool(
        re.search(r"createServer\s*\([^;]*\bhandleRequest\s*\(", source, re.DOTALL)
    )


def _sveltekit_route_path(file: str, filename: str) -> str | None:
    parts = file.split("/")
    try:
        route_index = max(index for index, part in enumerate(parts) if part == "routes")
    except ValueError:
        return None
    route_parts = [
        part
        for part in parts[route_index + 1 :]
        if part != filename and not (part.startswith("(") and part.endswith(")"))
    ]
    return "/" + "/".join(route_parts) if route_parts else "/"


def detect_sveltekit_pages(conn: sqlite3.Connection) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT path FROM files WHERE path LIKE '%/routes/%' OR path LIKE 'routes/%'"
    ).fetchall()
    entries = []
    for (file,) in rows:
        if file.endswith("/+page.svelte"):
            filename, role, symbol = "+page.svelte", "page_component", "+page"
        elif file.endswith("/+layout.svelte"):
            filename, role, symbol = "+layout.svelte", "page_layout", "+layout"
        else:
            continue
        if is_generated_or_vendored_path(file) or is_scaffold_template_path(file):
            continue
        path = _sveltekit_route_path(file, filename)
        if path is not None:
            entries.append({"file": file, "symbol": symbol, "role": role, "path": path})
    return sorted(entries, key=lambda item: item["file"])


def detect_sveltekit_server_routes(conn: sqlite3.Connection) -> list[Entrypoint]:
    methods = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD")
    placeholders = ",".join("?" for _ in methods)
    rows = conn.execute(
        f"SELECT e.id, f.path, e.name FROM entities e JOIN files f ON f.id=e.file_id "  # noqa: S608 - Only the generated placeholder count is interpolated.
        f"""
            WHERE e.kind=? AND f.is_test_path=0
              AND (f.path LIKE '%/routes/%/+server.%'
                   OR f.path LIKE 'routes/%/+server.%')
              AND e.name IN ({placeholders}) AND EXISTS (
                SELECT 1 FROM entities x WHERE x.file_id=e.file_id
                    AND x.kind=? AND x.name=e.name
              )""",
        (EntityKind.FUNCTION.as_i64(), *methods, EntityKind.EXPORT.as_i64()),
    ).fetchall()
    results = []
    for entity_id, file, method in rows:
        if is_generated_or_vendored_path(file) or is_scaffold_template_path(file):
            continue
        path = _sveltekit_route_path(file, file.rsplit("/", 1)[-1])
        if path is not None:
            results.append(
                Entrypoint(
                    entity_id, file, method, RoleTag.ROUTE_HANDLER, True, method, path
                )
            )
    return sorted(results, key=lambda item: (item.file, item.symbol))


def _handler_index(
    conn: sqlite3.Connection, names: list[str]
) -> dict[tuple[int | None, str], int]:
    if not names:
        return {}
    placeholders = ", ".join("?" for _ in names)
    rows = conn.execute(
        f"SELECT id, file_id, name FROM entities WHERE kind = ? "  # noqa: S608 - Generated placeholder count.
        f"AND name IN ({placeholders})",
        (EntityKind.FUNCTION.as_i64(), *names),
    ).fetchall()
    by_name: dict[str, list[tuple[int, int]]] = {}
    for entity_id, file_id, name in rows:
        by_name.setdefault(name, []).append((file_id, entity_id))
    result: dict[tuple[int | None, str], int] = {}
    for name, matches in by_name.items():
        if len(matches) == 1:
            result[(None, name)] = matches[0][1]
        for file_id, entity_id in matches:
            result[(file_id, name)] = entity_id
    return result


def _excluded_path(path: str) -> bool:
    return (
        is_generated_or_vendored_path(path)
        or is_scaffold_template_path(path)
        or is_frontend_asset_path(path)
    )


def _call_route_language(path: str) -> bool:
    return language_for_path(Path(path)) in {
        "go",
        "javascript",
        "typescript",
        "tsx",
        "php",
        "ruby",
        "csharp",
        "kotlin",
        "swift",
        "elixir",
    }
