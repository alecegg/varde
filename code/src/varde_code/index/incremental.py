"""Content-hash based incremental refresh for the code index."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from varde_code.index.files import SourceFile, _content_hash
from varde_code.index.lexical import index_outputs, lexical_available
from varde_code.index.provenance import record_built, refresh_provenance_if_due
from varde_code.seams import ExtractionProvider


class FileClassification:
    path: str
    status: str
    source: SourceFile | None
    __slots__ = ("path", "status", "source")

    def __init__(
        self, path: str, status: str, source: SourceFile | None = None
    ) -> None:
        for name, value in zip(self.__slots__, (path, status, source), strict=True):
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value) -> None:
        raise AttributeError(f"{type(self).__name__!r} object is frozen")

    def __delattr__(self, name) -> None:
        raise AttributeError(f"{type(self).__name__!r} object is frozen")

    def __eq__(self, other) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return (self.path, self.status, self.source) == (
            other.path,
            other.status,
            other.source,
        )

    def __repr__(self) -> str:
        return f"FileClassification(path={self.path!r}, status={self.status!r}, source={self.source!r})"

    def __hash__(self) -> int:
        return hash((self.path, self.status, self.source))


class BuildSummary:
    db_path: str
    entities: int
    symbols: int
    diagnostics: int
    unchanged: int
    reparsed: int
    changed_files: tuple[str, ...]
    __slots__ = (
        "db_path",
        "entities",
        "symbols",
        "diagnostics",
        "unchanged",
        "reparsed",
        "changed_files",
    )

    def __init__(
        self,
        db_path: str,
        entities: int,
        symbols: int,
        diagnostics: int,
        unchanged: int,
        reparsed: int,
        changed_files: tuple[str, ...],
    ) -> None:
        values = (
            db_path,
            entities,
            symbols,
            diagnostics,
            unchanged,
            reparsed,
            changed_files,
        )
        for name, value in zip(self.__slots__, values, strict=True):
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value) -> None:
        raise AttributeError(f"{type(self).__name__!r} object is frozen")

    def __delattr__(self, name) -> None:
        raise AttributeError(f"{type(self).__name__!r} object is frozen")

    def __eq__(self, other) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return all(
            getattr(self, name) == getattr(other, name) for name in self.__slots__
        )

    def __repr__(self) -> str:
        fields = ", ".join(f"{name}={getattr(self, name)!r}" for name in self.__slots__)
        return f"{type(self).__name__}({fields})"

    def __hash__(self) -> int:
        return hash(tuple(getattr(self, name) for name in self.__slots__))


def refresh(repo_root: str | Path, extractor: ExtractionProvider) -> BuildSummary:
    """Refresh changed files and re-resolve their reverse-dependent scope."""
    from varde_code.index._refresh_fastpath import unchanged_summary

    summary = unchanged_summary(repo_root)
    if summary is not None:
        refresh_provenance_if_due(Path(summary[0]), Path(repo_root))
        return BuildSummary(
            str(summary[0]),
            _database_count(summary[1]),
            _database_count(summary[2]),
            _database_count(summary[3]),
            _database_count(summary[4]),
            _database_count(summary[5]),
            _changed_paths(summary[6]),
        )

    import sqlite3

    from varde_code.index.db import SCHEMA_VERSION, build_version_fingerprint
    from varde_code.index.files import indexed_source_files, list_source_listing
    from varde_code.index.paths import repo_db_path
    from varde_code.index.repo_lock import acquire

    root = Path(repo_root).resolve(strict=True)
    db_path = repo_db_path(root)
    if not _incremental_state_valid(
        db_path, sqlite3, SCHEMA_VERSION, build_version_fingerprint
    ):
        from varde_code.index.build import run_full

        summary = run_full(root, db_path, extractor)
        return BuildSummary(
            summary.db_path,
            summary.entities,
            summary.symbols,
            summary.diagnostics,
            0,
            len(summary.changed_files),
            summary.changed_files,
        )

    with acquire(db_path):
        uri = f"file:{db_path}?mode=ro"
        with sqlite3.connect(uri, uri=True) as reader:
            stored = {
                path: (mtime, size, content_hash, file_id)
                for file_id, path, mtime, size, content_hash in reader.execute(
                    "SELECT id,path,mtime,size,content_hash FROM files"
                )
            }
            listing = list_source_listing(root)
            classifications = _classify_metadata(
                stored, indexed_source_files(listing.files)
            )
            _hash_changed_sources(classifications)
            changed = [
                item for item in classifications if item.status in {"changed", "new"}
            ]
            deleted = [
                item.path for item in classifications if item.status == "deleted"
            ]
            unchanged = sum(item.status == "unchanged" for item in classifications)
            current_walk_diagnostics = _current_null_diagnostics(
                listing.files, listing.diagnostics
            )
            stored_walk_diagnostics = reader.execute(
                "SELECT path,message,severity FROM diagnostics WHERE file_id IS NULL ORDER BY path,message,severity"
            ).fetchall()
            if (
                not changed
                and not deleted
                and current_walk_diagnostics == stored_walk_diagnostics
            ):
                counts = reader.execute(
                    "SELECT (SELECT COUNT(*) FROM entities), (SELECT COUNT(*) FROM symbols), "
                    "(SELECT COUNT(*) FROM diagnostics)"
                ).fetchone()
                if counts is None:
                    raise sqlite3.DatabaseError("index counts could not be read")
                if len(counts) != 3:
                    raise sqlite3.DatabaseError("index counts are incomplete")
                count_values = list(counts)
                entity_count = _database_count(count_values[0])
                symbol_count = _database_count(count_values[1])
                diagnostic_count = _database_count(count_values[2])
                refresh_provenance_if_due(db_path, root)
                return BuildSummary(
                    str(db_path),
                    entity_count,
                    symbol_count,
                    diagnostic_count,
                    unchanged,
                    0,
                    (),
                )

        connection = sqlite3.connect(db_path)
        try:
            return _refresh_changes(
                connection,
                root,
                db_path,
                extractor,
                changed,
                deleted,
                unchanged,
                stored,
                listing,
            )
        finally:
            connection.close()


def _refresh_changes(
    connection, root, db_path, extractor, changed, deleted, unchanged, stored, listing
) -> BuildSummary:
    from varde_code.index.build import _extract_files
    from varde_code.index.persist.entities import FileIds, write_entities, write_symbols
    from varde_code.index.persist.metrics import write_function_metrics
    from varde_code.model import FileMeta
    from varde_code.parse import language_for_path

    old_ids = {path: values[3] for path, values in stored.items()}
    changed_sources = [item for item in changed if item.source is not None]
    outputs = _extract_files([item.source for item in changed_sources], extractor)
    next_rev = connection.execute(
        "SELECT value FROM slice_meta WHERE key='next_rev'"
    ).fetchone()
    max_rev = connection.execute("SELECT COALESCE(MAX(rev),0) FROM files").fetchone()[0]
    allocated_rev = max(next_rev[0] if next_rev is not None else 1, max_rev + 1)
    source_revision_changed = any(
        language_for_path(item.path) is not None for item in changed
    ) or any(language_for_path(path) is not None for path in deleted)
    rev = allocated_rev if source_revision_changed else max_rev
    connection.execute("BEGIN")
    for path in deleted:
        _delete_file(connection, old_ids[path])
    for item in changed:
        source = item.source
        assert source is not None
        content_hash = source.content_hash or ""
        if language_for_path(source.path) is None:
            content_hash = _content_hash(b"")
        if item.status == "new":
            connection.execute(
                "INSERT INTO files(path,mtime,size,content_hash,rev) VALUES (?,?,?,?,?)",
                (source.path, source.mtime, source.size, content_hash, rev),
            )
            continue
        file_id = old_ids[item.path]
        _delete_file_rows(connection, file_id)
        connection.execute(
            "UPDATE files SET mtime=?,size=?,content_hash=?,rev=? WHERE id=?",
            (source.mtime, source.size, content_hash, rev, file_id),
        )
    file_ids_by_path = dict(connection.execute("SELECT path,id FROM files"))
    output_file_ids = []
    for output, item in zip(outputs, changed_sources, strict=True):
        file_id = file_ids_by_path[item.path]
        output.files = [item.path]
        output.file_meta = [
            FileMeta(
                item.source.mtime, item.source.size, item.source.content_hash or ""
            )
        ]
        output_file_ids.append(file_id)
    file_ids = FileIds(output_file_ids, list(range(len(output_file_ids))))
    entity_ids = write_entities(connection, outputs, file_ids)
    index_outputs(connection, outputs, file_ids, entity_ids)
    write_symbols(connection, outputs, file_ids)
    write_function_metrics(connection, outputs, file_ids)
    connection.execute("DELETE FROM diagnostics WHERE file_id IS NULL")
    _write_diagnostics(connection, outputs, output_file_ids, listing.diagnostics)
    _write_churn(
        connection,
        [
            item.path
            for item in changed_sources
            if language_for_path(item.path) is not None
        ],
        root,
    )
    max_rev = connection.execute("SELECT COALESCE(MAX(rev),0) FROM files").fetchone()[0]
    _resolve_and_persist(connection, root, max_rev)
    if source_revision_changed:
        connection.execute(
            "UPDATE slice_meta SET value=? WHERE key='next_rev'", (allocated_rev + 1,)
        )
    connection.execute("UPDATE slice_state SET built_through_rev=?", (max_rev,))
    record_built(connection, root)
    connection.commit()
    from varde_code.index.prune import record_source_root

    record_source_root(db_path, root)
    entity_count, symbol_count, diagnostic_count = connection.execute(
        "SELECT (SELECT COUNT(*) FROM entities), (SELECT COUNT(*) FROM symbols), "
        "(SELECT COUNT(*) FROM diagnostics)"
    ).fetchone()
    return BuildSummary(
        str(db_path),
        entity_count,
        symbol_count,
        diagnostic_count,
        unchanged,
        len(changed_sources),
        tuple(item.path for item in changed_sources),
    )


def classify_files(
    stored: dict[str, str], current: list[SourceFile]
) -> list[FileClassification]:
    """Compare stored content hashes with the current source listing."""
    by_path = {item.path: item for item in current}
    result = [
        FileClassification(
            path, "unchanged" if stored[path] == item.content_hash else "changed", item
        )
        for path, item in by_path.items()
        if path in stored
    ]
    result.extend(
        FileClassification(path, "new", item)
        for path, item in by_path.items()
        if path not in stored
    )
    result.extend(
        FileClassification(path, "deleted") for path in stored if path not in by_path
    )
    return sorted(result, key=lambda item: item.path)


def _classify_metadata(stored, current):
    from dataclasses import replace

    by_path = {item.path: item for item in current}
    result = []
    for path, source in by_path.items():
        previous = stored.get(path)
        if previous is None:
            result.append(FileClassification(path, "new", source))
            continue
        _, _, old_hash, _ = previous
        if source.mtime == previous[0] and source.size == previous[1]:
            if source.mtime != -1 or source.size != -1:
                if not old_hash:
                    result.append(FileClassification(path, "changed", source))
                    continue
                result.append(
                    FileClassification(
                        path, "unchanged", replace(source, content_hash=old_hash)
                    )
                )
                continue
            try:
                digest = _content_hash(Path(path).read_bytes())
            except OSError:
                digest = ""
            result.append(
                FileClassification(
                    path,
                    "unchanged" if digest == old_hash else "changed",
                    replace(source, content_hash=digest),
                )
            )
            continue
        result.append(FileClassification(path, "changed", source))
    result.extend(
        FileClassification(path, "deleted") for path in stored if path not in by_path
    )
    return sorted(result, key=lambda item: item.path)


def _hash_changed_sources(classifications):
    from dataclasses import replace
    from pathlib import Path

    for index, item in enumerate(classifications):
        if item.status not in {"changed", "new"} or item.source is None:
            continue
        try:
            digest = _content_hash(Path(item.path).read_bytes())
        except OSError:
            digest = ""
        classifications[index] = FileClassification(
            item.path,
            item.status,
            replace(item.source, content_hash=digest),
        )


def _delete_file_rows(connection, file_id: int) -> None:
    if lexical_available(connection):
        connection.execute(
            "DELETE FROM lexical WHERE rowid IN (SELECT id FROM entities WHERE file_id=?)",
            (file_id,),
        )
    for table in ("entities", "symbols", "diagnostics", "function_metrics"):
        connection.execute(f"DELETE FROM {table} WHERE file_id=?", (file_id,))


def _delete_file(connection, file_id: int) -> None:
    _delete_file_rows(connection, file_id)
    connection.execute(
        "DELETE FROM resolved_edges WHERE from_file_id=? OR to_file_id=?",
        (file_id, file_id),
    )
    connection.execute("DELETE FROM community_members WHERE file_id=?", (file_id,))
    connection.execute("DELETE FROM files WHERE id=?", (file_id,))


def _write_diagnostics(connection, outputs, file_ids, unsupported) -> None:
    rows = [(None, item.path, item.message, item.severity) for item in unsupported]
    for file_id, output in zip(file_ids, outputs, strict=True):
        rows.extend(
            (file_id, item.path, item.message, item.severity)
            for item in output.diagnostics
        )
    connection.executemany(
        "INSERT INTO diagnostics(file_id,path,message,severity) VALUES (?,?,?,?)", rows
    )


def _resolve_and_persist(connection, root: Path, rev: int) -> None:
    import json

    from varde_code.index.build import _graph_from_resolution, _write_derived_rows
    from varde_code.index.paths import repo_identity
    from varde_code.index.persist.edges import PersistedState, rewrite_edges
    from varde_code.index.resolve.core import resolve

    rows = connection.execute(
        "SELECT e.id,e.kind,e.name,e.file_id,f.path FROM entities e JOIN files f ON f.id=e.file_id ORDER BY e.id"
    ).fetchall()
    file_rows = connection.execute("SELECT id,path FROM files ORDER BY id").fetchall()
    ids = [row[0] for row in file_rows]
    files = [row[1] for row in file_rows]
    position = {file_id: index for index, file_id in enumerate(ids)}
    entities: list[Mapping[str, object]] = [
        {"kind": row[1], "name": row[2], "file_id": position[row[3]]} for row in rows
    ]
    entity_ids = [row[0] for row in rows]
    resolved: dict[str, Any] = resolve(entities, [], files)
    state = PersistedState(
        entities, entity_ids, files, ids, {file_id: i for i, file_id in enumerate(ids)}
    )
    connection.execute("DELETE FROM resolved_edges")
    rewrite_edges(connection, state, resolved["edges"], resolved["nodes"])
    connection.execute("DELETE FROM community_members")
    connection.execute("DELETE FROM communities")
    connection.execute("DELETE FROM clone_band_members")
    connection.execute("DELETE FROM clone_bands")
    _write_derived_rows(connection, resolved, ids)
    graph_entities = [dict(entity) for entity in entities]
    graph = _graph_from_resolution(files, resolved["edges"], graph_entities)
    blob = json.dumps(graph.to_dict(), separators=(",", ":"), sort_keys=True).encode()
    connection.execute(
        "INSERT INTO graph_cache(id,blob,rev) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET blob=excluded.blob,rev=excluded.rev",
        (blob, rev),
    )
    connection.execute(
        "UPDATE slice_meta SET value=? WHERE key='source_root'", (repo_identity(root),)
    )


def _write_churn(connection, files, root) -> None:
    from varde_code.index.churn import commit_counts_batch

    counts = commit_counts_batch(files, root)
    connection.executemany(
        "UPDATE files SET churn=? WHERE path=?",
        ((count, path) for path, count in counts.items()),
    )


def _database_count(value: object) -> int:
    if not isinstance(value, int):
        raise sqlite3.DatabaseError("index count is not an integer")
    return value


def _changed_paths(value: object) -> tuple[str, ...]:
    if isinstance(value, tuple) and all(isinstance(path, str) for path in value):
        return value
    raise TypeError("changed file paths are invalid")


def _walk_diagnostic_rows(diagnostics):
    return sorted((item.path, item.message, item.severity) for item in diagnostics)


def _current_null_diagnostics(files, walk_diagnostics):
    del files
    return _walk_diagnostic_rows(walk_diagnostics)


def _incremental_state_valid(
    db_path: Path, sqlite3, schema_version, fingerprint
) -> bool:
    if not db_path.is_file():
        return False
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
            return connection.execute("PRAGMA user_version").fetchone()[
                0
            ] == schema_version and connection.execute(
                "SELECT value FROM slice_meta WHERE key='build_version'"
            ).fetchone() == (fingerprint(),)
    except sqlite3.Error:
        return False
