"""Derived SQLite FTS5 index over entries. Files stay the source of truth.

The index file lives in `<local share>/varde/memory-index/`, beside the memory
root and never inside a memory root or a source bundle. Commands refresh it;
the SessionStart hook only reads it through `read_entry_rows` and scans files
when that returns None.

The file uses the default rollback journal, not WAL: a rebuild replaces the
file by rename, and WAL sidecar files left by the replaced file could be
applied to the new one. Readers open it with `mode=ro`.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import tempfile
from collections.abc import Callable, Iterable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from varde_core.paths import local_share_dir

from varde_learn.memory import sources, store
from varde_learn.memory.entry import SCOPES, Entry, summary_of
from varde_learn.memory.rules import Issue

SCHEMA_VERSION = 2
INDEX_DIR = ("varde", "memory-index")
FTS_COLUMNS = (
    "title",
    "aliases",
    "tags",
    "description",
    "summary",
    "topic",
    "slug",
    "extra",
    "body",
)
ENTRY_COLUMNS = (
    "path",
    "id",
    "scope",
    "scope_key",
    "type",
    "topic",
    "status",
    "valid_until",
    "surface",
    "created",
    "title",
    "aliases",
    "description",
)
Manifest = dict[str, tuple[int, int]]


@dataclass(frozen=True)
class Source:
    """Where entries come from: their files, a loader and each entry's file."""

    files: Callable[[], list[Path]]
    load: Callable[[], tuple[list[Entry], list[Issue]]]
    path_of: Callable[[Entry], Path]


@dataclass(frozen=True)
class IndexStats:
    entries: int
    indexed: int
    reused: int
    removed: int
    fts: bool
    persisted: bool


def memory_source(root: Path) -> Source:
    return Source(
        files=lambda: sorted(p for s in SCOPES for p in _md(root / s)),
        load=lambda: sources.load_memory(root),
        path_of=lambda e: store.entry_path(root, e.scope, e.scope_key, e.id),
    )


def bundle_source(bundle: Path, *, scope_key: str) -> Source:
    def path_of(entry: Entry) -> Path:
        slug = entry.source.removeprefix(f"knowledge:{bundle.name}:")
        return bundle / f"{slug}.md"

    return Source(
        files=lambda: list(sources.concept_files(bundle)),
        load=lambda: sources.load_bundle(bundle, scope_key=scope_key),
        path_of=path_of,
    )


def index_file_for(root: Path, data: Path | None = None) -> Path:
    """Index file for a root, under the local share tree that holds the memory root."""
    base = data if data is not None else local_share_dir()
    digest = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:12]
    return base.joinpath(*INDEX_DIR) / f"{digest}.sqlite"


def slug_text(entry: Entry) -> str:
    """The id plus a knowledge concept's original slug (its `/` parts count)."""
    parts = entry.source.split(":", 2)
    original = parts[2] if parts[0] == "knowledge" and len(parts) == 3 else ""
    return f"{entry.id} {original}".strip()


def flatten_values(value: object) -> str:
    """Every scalar inside an `extra` value, joined by spaces."""
    if isinstance(value, dict):
        return " ".join(flatten_values(item) for item in value.values())
    if isinstance(value, list | tuple):
        return " ".join(flatten_values(item) for item in value)
    return "" if value is None else str(value)


def fts5_available() -> bool:
    """Probe for FTS5 at runtime; the interpreter may differ from build time."""
    with closing(sqlite3.connect(":memory:")) as probe:
        try:
            probe.execute("CREATE VIRTUAL TABLE temp.fts_probe USING fts5(x)")
        except sqlite3.OperationalError:
            return False
    return True


def scan_manifest(files: Iterable[Path]) -> Manifest:
    """Path to (size, st_mtime_ns) for every readable file."""
    manifest: Manifest = {}
    for path in files:
        try:
            info = path.stat()
        except OSError:
            continue
        manifest[str(path)] = (info.st_size, info.st_mtime_ns)
    return manifest


def rebuild_index(source: Source, index_file: Path | None) -> IndexStats:
    """Build the whole index; a file is written to a temp file, then renamed."""
    if index_file is None:
        with closing(sqlite3.connect(":memory:")) as conn:
            return _fill(conn, source, persisted=False)
    index_file.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=index_file.parent, suffix=".tmp")
    os.close(handle)
    try:
        with closing(sqlite3.connect(temporary)) as conn:
            stats = _fill(conn, source, persisted=True)
        _fsync(Path(temporary))
        os.replace(temporary, index_file)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return stats


def refresh_index(source: Source, index_file: Path | None) -> IndexStats:
    """Update changed files in place; rebuild when the index is missing or bad."""
    if index_file is None or not index_file.exists():
        return rebuild_index(source, index_file)
    try:
        with closing(sqlite3.connect(index_file, timeout=10)) as conn:
            if _schema_version(conn) != SCHEMA_VERSION or _lacks_fts(conn):
                return rebuild_index(source, index_file)
            return _refresh(conn, source)
    except sqlite3.DatabaseError:
        return rebuild_index(source, index_file)


def connect(source: Source, index_file: Path | None) -> sqlite3.Connection:
    """A fresh index for a command: refreshed file, or an in-memory build."""
    if index_file is None:
        conn = sqlite3.connect(":memory:")
        _fill(conn, source, persisted=False)
        return conn
    try:
        refresh_index(source, index_file)
        return sqlite3.connect(index_file, timeout=10)
    except OSError as error:
        print(
            f"notice: search index not writable ({error}); using an in-memory index",
            file=sys.stderr,
        )
        return connect(source, None)


def read_entry_rows(source: Source, index_file: Path | None) -> list[dict] | None:
    """Hook read: `entries` rows when the index is current, else None (scan files).

    Never builds, refreshes or writes.
    """
    if index_file is None or not index_file.exists():
        return None
    try:
        with closing(sqlite3.connect(f"file:{index_file}?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            if _schema_version(conn) != SCHEMA_VERSION:
                return None
            if _stored_manifest(conn) != scan_manifest(source.files()):
                return None
            rows = conn.execute("SELECT * FROM entries ORDER BY path").fetchall()
    except sqlite3.Error:
        return None
    return [dict(row) for row in rows]


def _fsync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _lacks_fts(conn: sqlite3.Connection) -> bool:
    return fts5_available() and not has_fts(conn)


def _md(directory: Path) -> list[Path]:
    return list(directory.rglob("*.md")) if directory.is_dir() else []


def _fill(conn: sqlite3.Connection, source: Source, *, persisted: bool) -> IndexStats:
    fts = _create_schema(conn)
    entries, _ = source.load()
    manifest = scan_manifest(source.files())
    with conn:
        _insert_manifest(conn, manifest)
        for entry in entries:
            _insert_entry(conn, entry, source.path_of(entry), fts=fts)
    return IndexStats(len(entries), len(entries), 0, 0, fts, persisted)


def _refresh(conn: sqlite3.Connection, source: Source) -> IndexStats:
    current = scan_manifest(source.files())
    stored = _stored_manifest(conn)
    changed = {p for p, stamp in current.items() if stored.get(p) != stamp}
    removed = set(stored) - set(current)
    fts = has_fts(conn)
    if not changed and not removed:
        count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        return IndexStats(count, 0, count, 0, fts, True)
    entries, _ = source.load()
    with conn:
        _delete_paths(conn, changed | removed, fts=fts)
        _insert_manifest(conn, {p: current[p] for p in changed})
        fresh = [e for e in entries if str(source.path_of(e)) in changed]
        for entry in fresh:
            _insert_entry(conn, entry, source.path_of(entry), fts=fts)
    total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    return IndexStats(total, len(fresh), total - len(fresh), len(removed), fts, True)


def _create_schema(conn: sqlite3.Connection) -> bool:
    fts = fts5_available()
    columns = ", ".join(ENTRY_COLUMNS[1:])
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
    conn.execute(
        "CREATE TABLE manifest (path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER)"
    )
    conn.execute(f"CREATE TABLE entries (path TEXT PRIMARY KEY, {columns})")
    if fts:
        conn.execute(
            f"CREATE VIRTUAL TABLE entries_fts USING fts5({', '.join(FTS_COLUMNS)})"
        )
    return fts


def _insert_manifest(conn: sqlite3.Connection, manifest: Manifest) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO manifest VALUES (?, ?, ?)",
        [(path, size, mtime) for path, (size, mtime) in manifest.items()],
    )


def _insert_entry(
    conn: sqlite3.Connection, entry: Entry, path: Path, *, fts: bool
) -> None:
    values = (
        str(path),
        entry.id,
        entry.scope,
        entry.scope_key,
        entry.type,
        entry.topic,
        entry.status,
        entry.valid_until,
        int(entry.surface),
        entry.created,
        entry.title,
        " ".join(entry.aliases),
        entry.description,
    )
    marks = ", ".join("?" * len(values))
    insert = f"INSERT OR REPLACE INTO entries VALUES ({marks})"  # noqa: S608
    cursor = conn.execute(insert, values)
    if not fts:
        return
    row = (
        entry.title,
        " ".join(entry.aliases),
        " ".join(entry.tags),
        entry.description,
        summary_of(entry),
        entry.topic,
        slug_text(entry),
        flatten_values(entry.extra),
        entry.text,
    )
    marks = ", ".join("?" * (len(row) + 1))
    columns = ", ".join(FTS_COLUMNS)
    insert = f"INSERT INTO entries_fts(rowid, {columns}) VALUES ({marks})"  # noqa: S608
    conn.execute(insert, (cursor.lastrowid, *row))


def _delete_paths(conn: sqlite3.Connection, paths: set[str], *, fts: bool) -> None:
    for path in paths:
        if fts:
            conn.execute(
                "DELETE FROM entries_fts WHERE rowid IN "
                "(SELECT rowid FROM entries WHERE path = ?)",
                (path,),
            )
        conn.execute("DELETE FROM entries WHERE path = ?", (path,))
        conn.execute("DELETE FROM manifest WHERE path = ?", (path,))


def _schema_version(conn: sqlite3.Connection) -> int | None:
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row else None


def _stored_manifest(conn: sqlite3.Connection) -> Manifest:
    rows = conn.execute("SELECT path, size, mtime_ns FROM manifest").fetchall()
    return {path: (size, mtime) for path, size, mtime in rows}


def has_fts(conn: sqlite3.Connection) -> bool:
    return _has_table(conn, "entries_fts")


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone()
    return row is not None
