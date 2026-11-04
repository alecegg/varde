"""Build scan-local dependency facts without changing the index schema."""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path

from varde_code.parse import EXTENSION_LANGUAGES, language_for_path
from varde_code.rules.dependency_facts import (
    c_cpp,
    csharp_swift,
    elixir_haskell,
    jvm,
    lua_bash,
    python,
    ruby_php,
    rust,
)
from varde_code.rules.dependency_facts.types import (
    EdgeRow,
    Fact,
    FactInput,
    FileRow,
    ImportRow,
)
from varde_code.seams import ExtractionProvider


def prepare(
    conn: sqlite3.Connection, repo_root: Path, provider: ExtractionProvider
) -> None:
    """Replace the TEMP dependency_facts table with certified scan facts."""
    root = Path(os.path.abspath(repo_root))
    try:
        root_stat = root.stat()
    except OSError as error:
        raise ValueError(f"stat repository root: {error}") from error
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError(f"repository root is not a directory: {root}")
    files = _load_files(conn, root)
    indexed = _indexed_paths(files)
    imports = _load_imports(conn, files)
    edges = _load_edges(conn)
    input = FactInput(files, imports, edges)
    facts = _go_facts(files, imports, edges)
    for module in (
        c_cpp,
        csharp_swift,
        elixir_haskell,
        jvm,
        lua_bash,
        python,
        ruby_php,
    ):
        facts.extend(module.facts(input))
    facts.extend(rust.facts(input, provider))
    facts.extend(_relative_facts(root, files, indexed, imports))
    facts.sort(
        key=lambda fact: (
            fact.from_unit,
            fact.to_unit or "",
            fact.source_entity_id,
            fact.specifier,
        )
    )
    unique: list[Fact] = []
    seen: set[tuple[int, int, str | None, str]] = set()
    for fact in facts:
        key = (fact.from_file_id, fact.source_entity_id, fact.to_unit, fact.certainty)
        if key not in seen:
            seen.add(key)
            unique.append(fact)
    _write_facts(conn, unique)


def _load_files(conn: sqlite3.Connection, root: Path) -> list[FileRow]:
    try:
        rows = conn.execute(
            "SELECT id, path, is_test_path, is_tooling_path FROM files ORDER BY id"
        ).fetchall()
    except sqlite3.Error as error:
        raise ValueError(f"load indexed files: {error}") from error
    files = []
    for file_id, stored_path, is_test, is_tooling in rows:
        physical = Path(stored_path)
        if not physical.is_absolute():
            physical = root / physical
        repository_file = _repository_path(root, physical)
        if repository_file is None:
            continue
        relative, physical = repository_file
        files.append(
            FileRow(
                file_id,
                str(stored_path),
                relative,
                physical,
                bool(is_test),
                bool(is_tooling),
            )
        )
    return files


def _load_imports(conn: sqlite3.Connection, files: list[FileRow]) -> list[ImportRow]:
    ids = {file.id for file in files}
    try:
        rows = conn.execute(
            "SELECT id, file_id, name, body_shape FROM entities "
            "WHERE kind = 9 ORDER BY id"
        ).fetchall()
    except sqlite3.Error as error:
        raise ValueError(f"load indexed imports: {error}") from error
    imports = []
    for entity_id, file_id, specifier, body_shape in rows:
        if file_id not in ids or not isinstance(specifier, str):
            continue
        imports.append(
            ImportRow(entity_id, file_id, specifier, body_shape == "type_only")
        )
    return imports


def _load_edges(conn: sqlite3.Connection) -> list[EdgeRow]:
    try:
        rows = conn.execute(
            "SELECT from_file_id, from_entity_id, to_file_id, resolved "
            "FROM resolved_edges "
            "WHERE kind = 1 ORDER BY id"
        ).fetchall()
    except sqlite3.Error as error:
        raise ValueError(f"load resolved import edges: {error}") from error
    return [
        EdgeRow(source, entity, target, bool(resolved))
        for source, entity, target, resolved in rows
    ]


def _write_facts(conn: sqlite3.Connection, facts: list[Fact]) -> None:
    try:
        conn.executescript(
            "DROP TABLE IF EXISTS temp.dependency_facts;"
            "CREATE TEMP TABLE dependency_facts ("
            "from_file_id INTEGER NOT NULL, from_unit TEXT NOT NULL, "
            "to_file_id INTEGER, "
            "to_unit TEXT, kind INTEGER NOT NULL, certainty TEXT NOT NULL, "
            "source_entity_id INTEGER NOT NULL, specifier TEXT NOT NULL);"
        )
        conn.executemany(
            "INSERT INTO temp.dependency_facts "
            "(from_file_id, from_unit, to_file_id, to_unit, kind, certainty, "
            "source_entity_id, specifier) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    f.from_file_id,
                    f.from_unit,
                    f.to_file_id,
                    f.to_unit,
                    f.kind,
                    f.certainty,
                    f.source_entity_id,
                    f.specifier,
                )
                for f in facts
            ],
        )
    except sqlite3.Error as error:
        raise ValueError(f"write dependency facts: {error}") from error


def _indexed_paths(files: list[FileRow]) -> dict[str, list[int]]:
    indexed: dict[str, list[int]] = {}
    for file in files:
        indexed.setdefault(file.relative, []).append(file.id)
    return indexed


def _go_facts(
    files: list[FileRow], imports: list[ImportRow], edges: list[EdgeRow]
) -> list[Fact]:
    by_id = {file.id: file for file in files}
    imports_by_id = {item.id: item for item in imports}
    grouped: dict[tuple[int, int, str], list[FileRow]] = {}
    for edge in edges:
        source = by_id.get(edge.from_file_id)
        imp = (
            imports_by_id.get(edge.from_entity_id)
            if edge.from_entity_id is not None
            else None
        )
        target = by_id.get(edge.to_file_id) if edge.to_file_id is not None else None
        if (
            not edge.resolved
            or source is None
            or imp is None
            or target is None
            or language_for_path(source.path) != "go"
            or language_for_path(target.path) != "go"
            or source.is_test
            or source.is_tooling
            or target.is_test
            or target.is_tooling
            or imp.type_only
        ):
            continue
        unit = _package_unit(target.relative)
        grouped.setdefault((source.id, imp.id, unit), []).append(target)
    facts = []
    for (source_id, entity_id, target_unit), targets in grouped.items():
        source = by_id[source_id]
        source_unit = _package_unit(source.relative)
        if source_unit == target_unit:
            continue
        target = min(
            {file.id: file for file in targets}.values(), key=lambda file: file.relative
        )
        try:
            metadata = target.physical.stat()
        except FileNotFoundError, NotADirectoryError:
            continue
        except OSError as error:
            raise ValueError(
                f"stat Go dependency target {target.physical}: {error}"
            ) from error
        if not stat.S_ISREG(metadata.st_mode):
            continue
        imp = imports_by_id[entity_id]
        facts.append(
            Fact(
                source.id,
                source_unit,
                target.id,
                target_unit,
                1,
                "certified",
                entity_id,
                imp.specifier,
            )
        )
    return facts


def _relative_facts(
    root: Path,
    files: list[FileRow],
    indexed: dict[str, list[int]],
    imports: list[ImportRow],
) -> list[Fact]:
    by_id = {file.id: file for file in files}
    facts = []
    for imp in imports:
        source = by_id.get(imp.file_id)
        if (
            source is None
            or source.is_test
            or source.is_tooling
            or imp.type_only
            or language_for_path(source.path) == "go"
        ):
            continue
        raw = (
            imp.specifier[1:-1]
            if len(imp.specifier) >= 2
            and imp.specifier[0] == imp.specifier[-1]
            and imp.specifier[0] in "\"'"
            else imp.specifier
        )
        if not raw.startswith(("./", "../")) or any(char in raw for char in "?#%!\\"):
            continue
        language = language_for_path(source.path)
        if language not in {"javascript", "typescript", "tsx", "dart", "solidity"}:
            continue
        base = _resolve_relative(source.relative, raw)
        if base is None:
            continue
        if Path(raw).suffix == "":
            exact = root / base
            if _metadata_if_exists(exact) is not None and exact.is_file():
                continue
            if _metadata_if_exists(exact / "package.json") is not None:
                continue
        candidates = _candidates(base, language, raw)
        physical: list[str] = []
        existing = False
        for candidate in candidates:
            path = root / candidate
            metadata = _metadata_if_exists(path)
            if metadata is not None:
                existing = True
                if stat.S_ISREG(metadata.st_mode) and candidate not in physical:
                    physical.append(candidate)
        indexed_targets = [
            file_id for path in physical for file_id in indexed.get(path, [])
        ]
        if len(physical) == 1 and len(indexed_targets) == 1:
            target = by_id.get(indexed_targets[0])
            if (
                target
                and not target.is_test
                and not target.is_tooling
                and target.id != source.id
            ):
                facts.append(
                    Fact(
                        source.id,
                        source.relative,
                        target.id,
                        target.relative,
                        1,
                        "certified",
                        imp.id,
                        imp.specifier,
                    )
                )
        elif (
            not physical
            and not existing
            and Path(raw).suffix.lower().lstrip(".") in EXTENSION_LANGUAGES
        ):
            facts.append(
                Fact(
                    source.id,
                    source.relative,
                    None,
                    None,
                    1,
                    "missing",
                    imp.id,
                    imp.specifier,
                )
            )
    return facts


def _package_unit(path: str) -> str:
    parent = Path(path).parent.as_posix()
    return parent if parent not in ("", ".") else "."


def _resolve_relative(source: str, specifier: str) -> str | None:
    parts = list(Path(source).parent.parts)
    for part in Path(specifier).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts) or None


def _candidates(base: str, language: str, raw_spec: str) -> list[str]:
    extension = Path(raw_spec).suffix.lstrip(".")
    aliases = {
        "js": (extension, "ts", "tsx"),
        "jsx": (extension, "tsx"),
        "mjs": (extension, "mts"),
        "cjs": (extension, "cts"),
    }
    if extension:
        extensions = aliases.get(extension.lower(), (extension,))
        candidates = [str(Path(base).with_suffix(f".{ext}")) for ext in extensions]
    else:
        if language not in {"javascript", "typescript", "tsx"}:
            return []
        candidates = [f"{base}.{ext}" for ext in EXTENSION_LANGUAGES]
        candidates += [
            f"{base}/{name}"
            for name in (
                "index.js",
                "index.jsx",
                "index.mjs",
                "index.cjs",
                "index.ts",
                "index.tsx",
                "__init__.py",
                "init.lua",
            )
        ]
    source_js = language in {"javascript", "typescript", "tsx"}
    output = []
    for candidate in candidates:
        target_language = language_for_path(candidate)
        same_js_family = source_js and target_language in {
            "javascript",
            "typescript",
            "tsx",
        }
        if (target_language == language or same_js_family) and candidate not in output:
            output.append(candidate)
    return sorted(output)


def _metadata_if_exists(path: Path):
    try:
        return path.stat()
    except FileNotFoundError, NotADirectoryError:
        return None
    except OSError as error:
        raise ValueError(f"stat dependency target {path}: {error}") from error


def _repository_path(root: Path, stored: Path) -> tuple[str, Path] | None:
    absolute = Path(os.path.abspath(stored if stored.is_absolute() else root / stored))
    try:
        relative = absolute.relative_to(root)
    except ValueError:
        canonical_root = _canonical_path(root)
        canonical_stored = _canonicalize_with_missing_tail(absolute)
        if canonical_stored is None:
            return None
        try:
            relative = canonical_stored.relative_to(canonical_root)
        except ValueError:
            return None
    relative_text = relative.as_posix()
    if not relative_text:
        return None
    return relative_text, absolute


def _canonical_path(path: Path) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"canonicalize repository root: {error}") from error


def _canonicalize_with_missing_tail(path: Path) -> Path | None:
    cursor = path
    tail = []
    while True:
        try:
            cursor.stat()
            break
        except FileNotFoundError:
            if cursor.name == "":
                return None
            tail.append(cursor.name)
            if cursor.parent == cursor:
                return None
            cursor = cursor.parent
        except OSError as error:
            raise ValueError(f"stat indexed path {cursor}: {error}") from error
    try:
        canonical = cursor.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"canonicalize indexed path {cursor}: {error}") from error
    for part in reversed(tail):
        canonical /= part
    return canonical
