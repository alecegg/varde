"""Slice freshness metadata and index-service boundary."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from varde_code.git import run_git
from varde_code.index.db import SCHEMA_VERSION, build_version_fingerprint
from varde_code.index.files import (
    SourceFile,
    _content_hash,
    indexed_source_files,
    list_source_listing,
)
from varde_code.index.paths import repo_db_path
from varde_code.parse import language_for_path
from varde_code.seams import ExtractionProvider


class Slice(StrEnum):
    RAW = "raw"
    CHURN = "churn"
    IMPORTS = "imports"
    EDGES = "edges"
    GLOBAL = "global"


@dataclass(frozen=True)
class Scope:
    """A file-local or repository-wide freshness scope."""

    file: Path | None = None

    @classmethod
    def for_file(cls, path: str | Path) -> Scope:
        return cls(Path(path))

    @classmethod
    def repo(cls) -> Scope:
        return cls()


MAX_SCOPED_FILES = 500
_DERIVED_SLICES = ("imports", "edges", "global")


def check_fresh(
    db_path: str | Path,
    repo_root: str | Path,
    slices: tuple[Slice, ...] = (Slice.GLOBAL,),
    scope: Scope | None = None,
) -> bool:
    """Check schema, source metadata, and requested derived-slice revisions."""
    return _check_fresh(db_path, repo_root, slices, scope, _same_files)


def check_content_fresh(db_path: str | Path, repo_root: str | Path) -> bool:
    """Like ``check_fresh`` at repo scope, but only real content changes count.

    A touched file with identical content and gitignored files are fresh; edits,
    new files, and deleted files are stale.
    """
    return _check_fresh(db_path, repo_root, (Slice.GLOBAL,), None, _same_content)


def _check_fresh(
    db_path: str | Path,
    repo_root: str | Path,
    slices: tuple[Slice, ...],
    scope: Scope | None,
    same_files: Callable[
        [list[tuple[str, int, int, str]], list[SourceFile], Path], bool
    ],
) -> bool:
    db_path = Path(db_path)
    root = Path(repo_root)
    scope = scope or Scope.repo()
    if not db_path.is_file():
        return False
    try:
        canonical_root = root.resolve(strict=True)
        with _open_read_only(db_path) as connection:
            if (
                connection.execute("PRAGMA user_version").fetchone()[0]
                != SCHEMA_VERSION
            ):
                return False
            if _meta_value(connection, "build_version") != build_version_fingerprint():
                return False
            if scope.file is not None:
                target = scope.file.resolve(strict=True)
                if not target.is_relative_to(canonical_root):
                    return False
                current = indexed_source_files(list_source_listing(target).files)
                stored_rows = connection.execute(
                    "SELECT path, mtime, size, content_hash FROM files WHERE path IN (?, ?)",
                    (str(scope.file), str(target)),
                ).fetchall()
            else:
                listing = list_source_listing(root)
                if listing.diagnostics:
                    return False
                current = indexed_source_files(listing.files)
                stored_rows = connection.execute(
                    "SELECT path, mtime, size, content_hash FROM files"
                ).fetchall()
            if not same_files(stored_rows, current, canonical_root):
                return False
            max_rev = connection.execute(
                "SELECT COALESCE(MAX(rev), 0) FROM files"
            ).fetchone()[0]
            for slice_name in _requested_derived(slices):
                row = connection.execute(
                    "SELECT built_through_rev, schema_version FROM slice_state WHERE slice = ?",
                    (slice_name,),
                ).fetchone()
                if row is None or row[0] < max_rev or row[1] != SCHEMA_VERSION:
                    return False
            return True
    except OSError, sqlite3.Error, ValueError:
        return False


def ensure_fresh(
    db_path: str | Path,
    repo_root: str | Path,
    slices: tuple[Slice, ...] = (Slice.GLOBAL,),
    scope: Scope | None = None,
    freshen: Callable[[Path, tuple[Slice, ...], Scope], None] | None = None,
) -> None:
    """Freshen requested slices through the supplied index builder."""
    scope = scope or Scope.repo()
    if check_fresh(db_path, repo_root, slices, scope):
        return
    if freshen is None:
        raise RuntimeError("index is stale and no slice freshener is configured")
    freshen(Path(repo_root), slices, scope)


def dump_state(
    repo_root: str | Path | None = None, *, db_path: str | Path | None = None
) -> dict[str, object]:
    """Return the persisted freshness ledger without building or modifying it."""
    if db_path is None:
        if repo_root is None:
            raise ValueError("repo_root or db_path required")
        db_path = repo_db_path(Path(repo_root))
    path = Path(db_path)
    if not path.exists():
        return {"db_path": path, "db": "missing"}
    with _open_read_only(path) as connection:
        max_rev = connection.execute(
            "SELECT COALESCE(MAX(rev), 0) FROM files"
        ).fetchone()[0]
        next_rev = _meta_value(connection, "next_rev") or 0
        slices: dict[str, dict[str, object]] = {}
        for name in _DERIVED_SLICES:
            row = connection.execute(
                "SELECT built_through_rev, schema_version FROM slice_state WHERE slice = ?",
                (name,),
            ).fetchone()
            built = row[0] if row is not None else None
            stale = (
                row is None
                or built is None
                or built < max_rev
                or row[1] != SCHEMA_VERSION
            )
            slices[name] = {
                "built_through_rev": built,
                "stale": stale,
            }
        return {
            "db_path": path,
            "max_rev": max_rev,
            "next_rev": next_rev,
            "slices": slices,
        }


def reverse_dependent_scope(
    connection: sqlite3.Connection, base_ids: list[int] | tuple[int, ...]
) -> set[int] | None:
    """Return changed files and resolved callers, or None when scope is too broad."""
    scope = set(base_ids)
    if not scope:
        return scope
    placeholders = ",".join("?" for _ in scope)
    names = [
        row[0]
        for row in connection.execute(
            f"SELECT path FROM files WHERE id IN ({placeholders})", tuple(scope)
        )
    ]
    paths = [Path(name) for name in names]
    if any(path.name in {"Cargo.toml", "go.mod"} for path in paths):
        return None
    if any(language_for_path(path) is not None for path in paths):
        rows = connection.execute("SELECT path FROM files")
        fallback_languages = {"csharp", "java", "kotlin", "scala", "swift"}
        if any(language_for_path(row[0]) in fallback_languages for row in rows):
            return None
    callers = connection.execute(
        f"SELECT DISTINCT from_file_id FROM resolved_edges "
        f"WHERE to_file_id IN ({placeholders})",
        tuple(scope),
    )
    scope.update(row[0] for row in callers)
    return scope if len(scope) <= MAX_SCOPED_FILES else None


class IndexService:
    """Implementation of the shared index-service protocol."""

    def __init__(
        self,
        provider: ExtractionProvider | None = None,
        *,
        freshener: Callable[[Path, tuple[Slice, ...], Scope], None] | None = None,
    ):
        if provider is not None and freshener is not None:
            raise ValueError("provide either provider or freshener, not both")
        if provider is not None:
            from varde_code.index.build import build

            def refresh_existing(
                root: Path, slices: tuple[Slice, ...], scope: Scope
            ) -> None:
                if repo_db_path(root).is_file():
                    from varde_code.index.incremental import refresh

                    refresh(root, provider)
                else:
                    build(root, provider)

            freshener = refresh_existing
        self._freshener = freshener

    def ensure_fresh(self, root: Path) -> None:
        ensure_fresh(repo_db_path(root), root, freshen=self._freshener)

    def check_fresh(self, root: Path, scope: object = None) -> bool:
        parsed_scope = _scope_from_value(scope)
        return check_fresh(repo_db_path(root), root, scope=parsed_scope)

    def dump_state(self, root: Path) -> dict[str, object]:
        return dump_state(root)

    def repo_db_path(self, root: Path) -> Path:
        return repo_db_path(root)


def _scope_from_value(value: object) -> Scope:
    if value is None:
        return Scope.repo()
    if isinstance(value, Scope):
        return value
    if isinstance(value, (str, Path)):
        return Scope.for_file(value)
    raise TypeError("scope must be a Scope, path, or None")


def _requested_derived(slices: tuple[Slice, ...]) -> tuple[str, ...]:
    requested = {Slice(item) for item in slices}
    result: list[str] = []
    if Slice.IMPORTS in requested:
        result.append("imports")
    if Slice.EDGES in requested:
        result.append("imports")
        result.append("edges")
    if Slice.GLOBAL in requested:
        result.extend(_DERIVED_SLICES)
    return tuple(dict.fromkeys(result))


def _same_files(
    rows: list[tuple[str, int, int, str]], current: list[SourceFile], root: Path
) -> bool:
    stored: dict[str, tuple[int, int, str]] = {}
    for path, mtime, size, content_hash in rows:
        normalized = _normalize_path(str(path), root)
        stored[normalized] = (mtime, size, content_hash)
    observed = {
        _normalize_path(file.path, root): (file.mtime, file.size, file.content_hash)
        for file in current
    }
    if stored.keys() != observed.keys():
        return False
    return all(
        old_mtime == new_mtime
        and old_size == new_size
        and (old_mtime != -1 or old_size != -1 or old_hash == new_hash)
        for path, (old_mtime, old_size, old_hash) in stored.items()
        for new_mtime, new_size, new_hash in (observed[path],)
    )


def _same_content(
    rows: list[tuple[str, int, int, str]], current: list[SourceFile], root: Path
) -> bool:
    ignored = _ignored_paths(root)
    stored = {_normalize_path(str(row[0]), root): row for row in rows}
    observed = {_normalize_path(file.path, root): file for file in current}
    stored = {path: row for path, row in stored.items() if path not in ignored}
    observed = {path: file for path, file in observed.items() if path not in ignored}
    if stored.keys() != observed.keys():
        return False
    return all(_same_file_content(stored[path], observed[path]) for path in stored)


def _same_file_content(row: tuple[str, int, int, str], file: SourceFile) -> bool:
    _path, old_mtime, old_size, old_hash = row
    if old_mtime == file.mtime and old_size == file.size:
        return True
    if language_for_path(file.path) is None:
        return True
    if old_size != file.size:
        return False
    try:
        return _content_hash(Path(file.path).read_bytes()) == old_hash
    except OSError:
        return False


def _ignored_paths(root: Path) -> set[str]:
    output = run_git(
        ["ls-files", "-z", "--others", "--ignored", "--exclude-standard"], root
    )
    if not output:
        return set()
    return {_normalize_path(name, root) for name in output.split("\0") if name}


def _normalize_path(value: str, root: Path) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    try:
        return str(path.resolve(strict=True))
    except OSError:
        return str(path)


def _meta_value(connection: sqlite3.Connection, key: str) -> int | None:
    try:
        row = connection.execute(
            "SELECT value FROM slice_meta WHERE key = ?", (key,)
        ).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row is not None else None


def _open_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
