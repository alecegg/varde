"""Full code-index build and slice freshener dispatch."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC
from pathlib import Path
from typing import Any

from varde_code.graph_model import Graph
from varde_code.index.files import SourceFile
from varde_code.index.lexical import index_outputs
from varde_code.index.provenance import record_built
from varde_code.index.slice import Scope, Slice
from varde_code.model import Diagnostic, Entity, ExtractOutput
from varde_code.seams import ExtractionProvider


class BuildSummary:
    db_path: str
    entities: int
    symbols: int
    diagnostics: int
    changed_files: tuple[str, ...]
    __slots__ = ("db_path", "entities", "symbols", "diagnostics", "changed_files")

    def __init__(self, db_path, entities, symbols, diagnostics, changed_files) -> None:
        for name, value in zip(
            self.__slots__,
            (db_path, entities, symbols, diagnostics, changed_files),
            strict=True,
        ):
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


def build(repo_root: str | Path, extractor: ExtractionProvider) -> BuildSummary:
    """Build the Python code index for ``repo_root``."""
    from varde_code.index.paths import repo_db_path

    root = Path(repo_root).resolve(strict=True)
    db_path = repo_db_path(root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return run_full(root, db_path, extractor)


def freshen(
    repo_root: Path,
    slices: tuple[Slice, ...],
    scope: Scope,
    extractor: ExtractionProvider | None = None,
) -> None:
    """IndexService-compatible callback; rebuild the repo when any slice is stale."""
    del slices, scope
    if extractor is None:
        raise RuntimeError(
            "an extraction provider is required to freshen the code index"
        )
    build(repo_root, extractor)


def make_freshener(
    extractor: ExtractionProvider,
) -> Callable[[Path, tuple[Slice, ...], Scope], None]:
    """Bind an extraction provider to the callback accepted by ``IndexService``."""

    def callback(repo_root: Path, slices: tuple[Slice, ...], scope: Scope) -> None:
        freshen(repo_root, slices, scope, extractor)

    return callback


def ensure_file_fresh(
    repo_root: str | Path, file_path: str | Path, extractor: ExtractionProvider
) -> None:
    """Refresh the requested file through a full build until targeted writes land."""
    root = Path(repo_root).resolve(strict=True)
    target = Path(file_path)
    if not target.is_absolute():
        target = root / target
    if target.exists():
        build(root, extractor)


def run_full(
    repo_root: Path,
    db_path: Path,
    extractor: ExtractionProvider,
) -> BuildSummary:
    """Write a complete index to a sibling temporary database, then replace it."""
    import os

    from varde_code.index.db import initialize
    from varde_code.index.files import list_source_listing
    from varde_code.index.repo_lock import acquire

    with acquire(db_path):
        listing = list_source_listing(repo_root)
        outputs = _extract_files(listing.files, extractor)
        temporary = db_path.with_suffix(".db.tmp")
        temporary.unlink(missing_ok=True)
        connection = initialize(temporary)
        try:
            _entity_ids, _file_ids, _graph = _persist(
                connection, outputs, listing.diagnostics, repo_root
            )
            entity_count = sum(len(output.entities) for output in outputs)
            symbol_count = connection.execute(
                "SELECT COUNT(*) FROM symbols"
            ).fetchone()[0]
            connection.commit()
        except BaseException:
            connection.close()
            temporary.unlink(missing_ok=True)
            raise
        connection.close()
        os.replace(temporary, db_path)
        from varde_code.index.prune import record_source_root

        record_source_root(db_path, repo_root)
    return BuildSummary(
        db_path=str(db_path),
        entities=entity_count,
        symbols=symbol_count,
        diagnostics=len(listing.diagnostics) + sum(len(o.diagnostics) for o in outputs),
        changed_files=tuple(file.path for file in listing.files),
    )


def _extract_files(
    files: Sequence[SourceFile], extractor: ExtractionProvider
) -> list[ExtractOutput]:
    import sys

    outputs = _extract_outputs(files, extractor)
    for file, output in zip(files, outputs, strict=True):
        _write_scan_warnings(output, file.path, sys.stderr)
    return outputs


_PARALLEL_MIN_FILES = 64
_MAX_WORKERS = 8
_worker_state: dict[str, ExtractionProvider] = {}


def _extract_outputs(
    files: Sequence[SourceFile], extractor: ExtractionProvider
) -> list[ExtractOutput]:
    import os
    import sys
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool

    cpu_count = getattr(os, "process_cpu_count", os.cpu_count)
    workers = min(cpu_count() or 1, _MAX_WORKERS)
    if workers <= 1 or len(files) < _PARALLEL_MIN_FILES:
        return [_extract_one(file, extractor) for file in files]
    try:
        pool = ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker,
            initargs=(extractor,),
        )
    except (OSError, ValueError, TypeError) as exc:
        print(f"index build: process pool unavailable: {exc}", file=sys.stderr)
        return [_extract_one(file, extractor) for file in files]
    try:
        outputs = list(pool.map(_extract_in_worker, files, chunksize=16))
    except (BrokenProcessPool, PermissionError) as exc:
        pool.shutdown(wait=False, cancel_futures=True)
        print(f"index build: process pool failed: {exc}", file=sys.stderr)
        return [_extract_one(file, extractor) for file in files]
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    return outputs


def _init_worker(extractor: ExtractionProvider) -> None:
    import contextlib
    import os

    _worker_state["extractor"] = extractor
    with contextlib.suppress(OSError):
        os.nice(10)


def _extract_in_worker(file: SourceFile) -> ExtractOutput:
    return _extract_one(file, _worker_state["extractor"])


def _extract_one(file: SourceFile, extractor: ExtractionProvider) -> ExtractOutput:
    from pathlib import Path

    from varde_code.index.files import _content_hash
    from varde_code.model import Diagnostic, ExtractOutput, FileMeta
    from varde_code.parse import language_for_path

    path = Path(file.path)
    language = language_for_path(path)
    if language is None:
        diagnostic = Diagnostic(0, file.path, "unsupported file type — skipped", "info")
        return ExtractOutput(
            diagnostics=[diagnostic],
            files=[file.path],
            file_meta=[FileMeta(file.mtime, file.size, _content_hash(b""))],
        )
    try:
        content = path.read_bytes()
    except OSError:
        return _skipped_output(
            file, "binary or non-UTF-8 — skipped", "error", content=None
        )
    try:
        source = content.decode("utf-8")
    except UnicodeError:
        return _skipped_output(file, "binary or non-UTF-8 — skipped", "error", content)
    from varde_code.query.noise_filter import is_minified_source

    if is_minified_source(source):
        return _skipped_output(
            file, "minified/generated source — skipped", "warning", content
        )
    output = extractor.extract(path, source, language)
    output.files = [file.path]
    content_hash = file.content_hash or _content_hash(content)
    output.file_meta = [FileMeta(file.mtime, file.size, content_hash)]
    return output


def _skipped_output(
    file, message: str, severity: str, content: bytes | None
) -> ExtractOutput:
    from varde_code.index.files import _content_hash
    from varde_code.model import Diagnostic, ExtractOutput, FileMeta

    return ExtractOutput(
        diagnostics=[Diagnostic(0, file.path, message, severity)],
        files=[file.path],
        file_meta=[FileMeta(file.mtime, file.size, _content_hash(content or b""))],
    )


def _write_scan_warnings(output: ExtractOutput, path: str, stream) -> None:
    from datetime import datetime

    for diagnostic in output.diagnostics:
        if diagnostic.severity not in {"warning", "error"}:
            continue
        detail = ""
        if diagnostic.message == "syntax error — partial extract kept":
            detail = f" entities={len(output.entities)} symbols={len(output.symbols)}"
        timestamp = (
            datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        )
        print(
            f"{timestamp}  WARN varde_code::scan: {diagnostic.message} file={path}{detail}",
            file=stream,
        )


def _persist(
    connection: sqlite3.Connection,
    outputs: Sequence[ExtractOutput],
    walk_diagnostics: Sequence[Diagnostic],
    repo_root: Path,
) -> tuple[list[int], list[int], Graph]:
    import json

    from varde_code.index.paths import repo_identity
    from varde_code.index.persist.edges import PersistedState, rewrite_edges
    from varde_code.index.persist.entities import (
        write_entities,
        write_files,
        write_symbols,
    )
    from varde_code.index.persist.metrics import write_function_metrics
    from varde_code.index.resolve.core import resolve

    file_ids = write_files(connection, outputs)
    from varde_code.index.churn import commit_counts_batch
    from varde_code.parse import language_for_path

    churn = commit_counts_batch(
        [
            path
            for output in outputs
            for path in output.files
            if language_for_path(path) is not None
        ],
        repo_root,
    )
    connection.executemany(
        "UPDATE files SET churn=? WHERE path=?",
        ((count, path) for path, count in churn.items()),
    )
    entity_ids = write_entities(connection, outputs, file_ids)
    index_outputs(connection, outputs, file_ids, entity_ids)
    write_symbols(connection, outputs, file_ids)
    write_function_metrics(connection, outputs, file_ids)
    files = [path for output in outputs for path in output.files]
    entities: list[Mapping[str, object]] = [
        {**_entity_mapping(entity), "file_id": file_index}
        for file_index, output in enumerate(outputs)
        for entity in output.entities
    ]
    symbols: list[dict[str, object]] = [
        {
            "kind": symbol.kind,
            "name": symbol.name,
            "file_id": file_index,
            "start_byte": symbol.span.start_byte,
            "end_byte": symbol.span.end_byte,
        }
        for file_index, output in enumerate(outputs)
        for symbol in output.symbols
    ]
    resolved: dict[str, Any] = resolve(entities, symbols, files)
    resolver_state = PersistedState(
        entities=entities,
        entity_ids=entity_ids,
        files=files,
        file_ids=file_ids.flat,
        file_index={db_id: index for index, db_id in enumerate(file_ids.flat)},
    )
    rewrite_edges(connection, resolver_state, resolved["edges"], resolved["nodes"])
    _write_derived_rows(connection, resolved, file_ids.flat)
    _write_diagnostics(connection, outputs, file_ids.flat, walk_diagnostics)
    _record_freshness(connection)
    graph = _graph_from_resolution(files, resolved["edges"], entities)
    blob = json.dumps(graph.to_dict(), separators=(",", ":"), sort_keys=True).encode()
    connection.execute("INSERT INTO graph_cache(id,blob,rev) VALUES (1,?,0)", (blob,))
    connection.execute(
        "INSERT INTO slice_meta(key,value) VALUES ('source_root',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (repo_identity(repo_root),),
    )
    record_built(connection, repo_root)
    return entity_ids, file_ids.flat, graph


def _entity_mapping(entity: Entity) -> dict[str, object]:
    return {
        "kind": entity.kind,
        "name": entity.name,
        "file_id": entity.file_id,
        "owner_type": entity.owner_type,
        "enclosing_function": entity.enclosing_function,
        "is_test": entity.is_test,
        "start_byte": entity.span.start_byte,
        "end_byte": entity.span.end_byte,
    }


def _write_derived_rows(
    connection: sqlite3.Connection, resolved: dict[str, Any], file_ids: Sequence[int]
) -> None:
    index_by_path = dict(
        zip((node["path"] for node in resolved["nodes"]), file_ids, strict=True)
    )
    for node in resolved["nodes"]:
        connection.execute(
            "UPDATE files SET community_id=?, fan_in=?, fan_out=? WHERE id=?",
            (
                int(node["community_id"]) + 1,
                node["fan_in"],
                node["fan_out"],
                index_by_path[node["path"]],
            ),
        )
    for community_index, community in enumerate(resolved["communities"]):
        community_id = community_index + 1
        connection.execute(
            "INSERT INTO communities(id,label) VALUES (?,?)",
            (community_id, f"community-{community_index}"),
        )
        connection.executemany(
            "INSERT INTO community_members(community_id,file_id) VALUES (?,?)",
            ((community_id, index_by_path[path]) for path in community["members"]),
        )
    for clone_band in resolved["clone_bands"]:
        cursor = connection.execute("INSERT INTO clone_bands(label) VALUES (?)", ("",))
        band_id = cursor.lastrowid
        connection.executemany(
            "INSERT INTO clone_band_members(band_id,entity_id) VALUES (?,?)",
            ((band_id, entity_id + 1) for entity_id in clone_band["members"]),
        )


def _write_diagnostics(
    connection: sqlite3.Connection,
    outputs: Sequence[ExtractOutput],
    file_ids: Sequence[int],
    walk_diagnostics: Sequence[Diagnostic],
) -> None:

    rows: list[tuple[int | None, str, str, str]] = [
        (None, item.path, item.message, item.severity) for item in walk_diagnostics
    ]
    for file_id, output in zip(file_ids, outputs, strict=True):
        rows.extend(
            (file_id, item.path, item.message, item.severity)
            for item in output.diagnostics
        )
    connection.executemany(
        "INSERT INTO diagnostics(file_id,path,message,severity) VALUES (?,?,?,?)", rows
    )


def _record_freshness(connection: sqlite3.Connection) -> None:
    from varde_code.index.db import SCHEMA_VERSION, build_version_fingerprint

    max_rev = connection.execute("SELECT COALESCE(MAX(rev),0) FROM files").fetchone()[0]
    connection.execute("DELETE FROM slice_state")
    connection.executemany(
        "INSERT INTO slice_state(slice,built_through_rev,schema_version) VALUES (?,?,?)",
        ((name, max_rev, SCHEMA_VERSION) for name in ("imports", "edges", "global")),
    )
    connection.execute(
        "INSERT INTO slice_meta(key,value) VALUES ('build_version',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (build_version_fingerprint(),),
    )
    connection.execute(
        "INSERT INTO slice_meta(key,value) VALUES ('next_rev',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (max_rev,),
    )


def _graph_from_resolution(
    files: Sequence[str],
    edges: Sequence[dict[str, object]],
    entities: Sequence[Mapping[str, object]],
) -> Graph:
    from varde_code.graph_model import Graph

    outgoing = {index: set() for index in range(len(files))}
    incoming = {index: set() for index in range(len(files))}
    for edge in edges:
        if not edge["resolved"]:
            continue
        source = edge["from"]
        target = edge["to"]
        if not isinstance(source, int) or not isinstance(target, Mapping):
            continue
        target_id = target["id"]
        if not isinstance(target_id, int):
            continue
        if target["target"] == "entity":
            target_entity = entities[target_id]
            file_id = target_entity["file_id"]
            if not isinstance(file_id, int):
                continue
            target_id = file_id
        outgoing[source].add(target_id)
        incoming[target_id].add(source)
    return Graph(
        paths=dict(enumerate(files)),
        out={key: sorted(value) for key, value in outgoing.items()},
        inc={key: sorted(value) for key, value in incoming.items()},
    )
