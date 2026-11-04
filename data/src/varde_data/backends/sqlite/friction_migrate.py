"""Migration of legacy learn databases into the canonical friction log."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from collections.abc import Mapping
from contextlib import closing, suppress
from pathlib import Path

from varde_data.backends.sqlite.friction_schema import (
    SCHEMA_VERSION,
    configure_store,
    database_has_rows,
    read_schema_version,
    table_exists,
)
from varde_data.errors import Invalid
from varde_data.friction_events import (
    append_many_checked_under_lock,
    fold,
    replay,
    unique_slug,
)
from varde_data.records.friction import (
    AdoptionRecorded,
    Event,
    ItemAdded,
    OccurrenceAppended,
    StatusChanged,
)

LOG_NAME = "friction.jsonl"
PRE_LOG_SUFFIX = ".pre-log"


def migration_map_path(database_path: Path) -> Path:
    return Path(f"{database_path}{PRE_LOG_SUFFIX}.map")


def prepare_store(store_dir: Path, database_path: Path) -> None:
    """Apply learn's migration predicate before every repository operation."""
    recover_interrupted_migration(store_dir, database_path)
    if not database_path.is_file():
        return
    with closing(sqlite3.connect(database_path)) as connection, connection:
        current = read_schema_version(connection)
        if current > SCHEMA_VERSION:
            raise Invalid(
                f"friction database version {current} is newer than supported "
                f"version {SCHEMA_VERSION}"
            )
        has_rows = database_has_rows(connection)
    if current >= 1 and has_rows and (not replay(store_dir).events or current < 4):
        migrate_database_to_log(store_dir, database_path)


def migrate_database_to_log(store_dir: Path, database_path: Path) -> None:
    with closing(sqlite3.connect(database_path)) as connection, connection:
        events, id_map = dump_database(connection)
    store_dir.mkdir(parents=True, exist_ok=True)
    backup_path = Path(f"{database_path}{PRE_LOG_SUFFIX}")
    if not backup_path.exists():
        shutil.copy2(database_path, backup_path)
    map_path = migration_map_path(database_path)
    _write_map(map_path, id_map)
    append_many_checked_under_lock(
        store_dir,
        lambda existing: (
            event
            for event in events
            if event.id not in {saved.id for saved in existing}
        ),
        redact=lambda value: (value, 0),
    )
    with closing(sqlite3.connect(database_path)) as connection, connection:
        configure_store(connection)
        rebuild_cache(connection, store_dir, id_map)
    with suppress(FileNotFoundError):
        map_path.unlink()


def recover_interrupted_migration(store_dir: Path, database_path: Path) -> None:
    map_path = migration_map_path(database_path)
    try:
        id_map = json.loads(map_path.read_text())
    except OSError, ValueError:
        return
    logged = {event.id for event in replay(store_dir).events}
    saved = id_map.get("items", {})
    if not saved or not set(saved).issubset(logged):
        return
    with closing(sqlite3.connect(database_path)) as connection, connection:
        configure_store(connection)
        rebuild_cache(connection, store_dir, id_map)
    with suppress(FileNotFoundError):
        map_path.unlink()


def rebuild_cache(
    connection: sqlite3.Connection,
    store_dir: Path,
    preserved: Mapping[str, Mapping[str, int | str]] | None = None,
) -> None:
    state = fold(replay(store_dir).events)
    log_path = store_dir / LOG_NAME
    raw = log_path.read_bytes() if log_path.exists() else b""
    complete = raw if not raw or raw.endswith(b"\n") else raw[: raw.rfind(b"\n") + 1]
    digest = hashlib.sha256(complete).hexdigest()
    connection.execute("BEGIN IMMEDIATE")
    try:
        id_map = _read_id_map(connection, {item.event_id for item in state.items})
        if preserved:
            for key, values in preserved.items():
                id_map.setdefault(key, {}).update(values)
        for table in (
            "adoption_items",
            "incident_provenance",
            "occurrences",
            "status_changes",
            "adoptions",
            "items",
            "item_tags",
        ):
            connection.execute(
                f'DELETE FROM "{table}"'  # noqa: S608 - fixed internal table names
            )
        item_ids = id_map.setdefault("items", {})
        slugs = id_map.setdefault("item_slugs", {})
        next_id = max((int(value) for value in item_ids.values()), default=0)
        taken = {str(value) for value in slugs.values()}
        mapping: dict[str, int] = {}
        for item in state.items:
            if item.event_id not in item_ids:
                next_id += 1
                item_ids[item.event_id] = next_id
            row_id = int(item_ids[item.event_id])
            mapping[item.event_id] = row_id
            slug = str(slugs.get(item.event_id) or unique_slug(taken, item.slug))
            slugs[item.event_id] = slug
            taken.add(slug)
            connection.execute(
                "INSERT INTO items(id,slug,title,source,repo_root,status,target,"
                "created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    row_id,
                    slug,
                    item.title,
                    item.source,
                    item.repo_root,
                    item.status,
                    item.target,
                    item.created_at,
                ),
            )
            connection.executemany(
                "INSERT INTO item_tags(item_id,tag) VALUES (?,?)",
                ((row_id, tag) for tag in item.tags),
            )
        _write_children(connection, state, mapping, id_map)
        _write_meta(connection, "schema_version", str(SCHEMA_VERSION))
        _write_meta(connection, "log_bytes", str(len(complete)))
        _write_meta(connection, "log_hash", digest)
        _write_meta(connection, "log_map", json.dumps(id_map, separators=(",", ":")))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def dump_database(
    connection: sqlite3.Connection,
) -> tuple[list[Event], dict[str, dict[str, int | str]]]:
    """Port of learn.store.log_sync.dump_database."""
    id_map: dict[str, dict[str, int | str]] = {
        "items": {},
        "item_slugs": {},
        "occurrences": {},
        "status_changes": {},
        "adoptions": {},
    }
    events: list[Event] = []
    item_events: dict[int, str] = {}
    last_ts: dict[int, str] = {}
    folded_status: dict[int, str] = {}
    items = (
        connection.execute(
            "SELECT id,slug,title,source,repo_root,status,target,created_at "
            "FROM items ORDER BY id"
        ).fetchall()
        if table_exists(connection, "items")
        else []
    )
    for item_id, slug, title, source, repo_root, _status, target, created_at in items:
        tags = (
            [
                row[0]
                for row in connection.execute(
                    "SELECT tag FROM item_tags WHERE item_id=? ORDER BY tag", (item_id,)
                )
            ]
            if table_exists(connection, "item_tags")
            else []
        )
        event = Event.at(
            created_at,
            repo_root,
            ItemAdded(title, source, repo_root, target, tags or None),
        )
        events.append(event)
        item_events[item_id] = event.id
        last_ts[item_id] = created_at
        id_map["items"][event.id] = item_id
        id_map["item_slugs"][event.id] = slug

    occurrences = (
        connection.execute(
            "SELECT id,item_id,at,cwd,repo_root,head_sha,evidence,cost "
            "FROM occurrences ORDER BY id"
        ).fetchall()
        if table_exists(connection, "occurrences")
        else []
    )
    for row_id, item_id, at, cwd, repo_root, head_sha, evidence, cost in occurrences:
        ts = next_dump_ts(last_ts[item_id], at)
        last_ts[item_id] = ts
        provenance = None
        if table_exists(connection, "incident_provenance"):
            row = connection.execute(
                "SELECT incident_key,identity_version,harness,thread_id,"
                "incident_kind,witness_id,source_id,record_index,byte_start,"
                "byte_end,record_digest,payload_digest FROM incident_provenance "
                "WHERE occurrence_id=?",
                (row_id,),
            ).fetchone()
            if row:
                keys = (
                    "incident_key",
                    "identity_version",
                    "harness",
                    "thread_id",
                    "incident_kind",
                    "witness_id",
                    "source_id",
                    "record_index",
                    "byte_start",
                    "byte_end",
                    "record_digest",
                    "payload_digest",
                )
                provenance = {
                    str(key): value for key, value in zip(keys, row, strict=False)
                }
        event = Event.at(
            ts,
            None,
            OccurrenceAppended(
                item_events[item_id],
                at,
                cwd,
                evidence,
                repo_root,
                head_sha,
                cost,
                provenance,
            ),
        )
        events.append(event)
        id_map["occurrences"][event.id] = row_id

    changes = (
        connection.execute(
            "SELECT id,item_id,at,from_status,to_status,reason "
            "FROM status_changes ORDER BY id"
        ).fetchall()
        if table_exists(connection, "status_changes")
        else []
    )
    for row_id, item_id, at, from_status, to_status, reason in changes:
        ts = next_dump_ts(last_ts[item_id], at)
        last_ts[item_id] = ts
        folded_status[item_id] = to_status
        event = Event.at(
            ts,
            None,
            StatusChanged(item_events[item_id], at, from_status, to_status, reason),
        )
        events.append(event)
        id_map["status_changes"][event.id] = row_id
    for item_id, _slug, _title, _source, _repo, stored, _target, _created in items:
        current = folded_status.get(item_id, "open")
        if current != stored:
            ts = bump_timestamp(last_ts[item_id])
            events.append(
                Event.at(
                    ts,
                    None,
                    StatusChanged(
                        item_events[item_id], ts, current, stored, "migrated status"
                    ),
                )
            )
            last_ts[item_id] = ts

    if table_exists(connection, "adoptions"):
        for row in connection.execute(
            "SELECT id,at,summary,target_files,commit_sha,eval_before,eval_after "
            "FROM adoptions ORDER BY id"
        ):
            row_id, at, summary, target_files, commit_sha, before, after = row
            item_ids = (
                [
                    item[0]
                    for item in connection.execute(
                        "SELECT item_id FROM adoption_items WHERE adoption_id=? "
                        "ORDER BY item_id",
                        (row_id,),
                    )
                ]
                if table_exists(connection, "adoption_items")
                else []
            )
            item_event_ids = [item_events[item_id] for item_id in item_ids]
            latest = max((last_ts[item_id] for item_id in item_ids), default="")
            ts = next_dump_ts(latest, at) if latest else at
            event = Event.at(
                ts,
                None,
                AdoptionRecorded(
                    at,
                    summary,
                    json.loads(target_files),
                    item_event_ids,
                    commit_sha,
                    before,
                    after,
                ),
            )
            events.append(event)
            id_map["adoptions"][event.id] = row_id
    return events, id_map


def _write_children(connection: sqlite3.Connection, state, item_ids, id_map) -> None:
    occurrence_ids = _stable_ids(
        state.occurrences, id_map.setdefault("occurrences", {})
    )
    status_ids = _stable_ids(
        state.status_changes, id_map.setdefault("status_changes", {})
    )
    adoption_ids = _stable_ids(state.adoptions, id_map.setdefault("adoptions", {}))
    for row in state.occurrences:
        if row.item_event_id not in item_ids:
            continue
        occurrence_id = occurrence_ids[row.event_id]
        connection.execute(
            "INSERT INTO occurrences VALUES(?,?,?,?,?,?,?,?)",
            (
                occurrence_id,
                item_ids[row.item_event_id],
                row.at or row.event_id,
                row.cwd,
                row.repo_root,
                row.head_sha,
                row.evidence,
                row.cost,
            ),
        )
        provenance = row.provenance
        if provenance:
            names = (
                "identity_version",
                "harness",
                "thread_id",
                "incident_kind",
                "witness_id",
                "source_id",
                "record_index",
                "byte_start",
                "byte_end",
                "record_digest",
                "payload_digest",
            )
            connection.execute(
                "INSERT INTO incident_provenance VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    provenance["incident_key"],
                    occurrence_id,
                    *(provenance.get(name) for name in names),
                ),
            )
    for row in state.status_changes:
        if row.item_event_id in item_ids:
            connection.execute(
                "INSERT INTO status_changes VALUES(?,?,?,?,?,?)",
                (
                    status_ids[row.event_id],
                    item_ids[row.item_event_id],
                    row.at,
                    row.from_,
                    row.to,
                    row.reason,
                ),
            )
    for row in state.adoptions:
        adoption_id = adoption_ids[row.event_id]
        connection.execute(
            "INSERT INTO adoptions VALUES(?,?,?,?,?,?,?)",
            (
                adoption_id,
                row.at,
                row.summary,
                json.dumps(row.files, separators=(",", ":")),
                row.commit_sha,
                row.eval_before,
                row.eval_after,
            ),
        )
        connection.executemany(
            "INSERT INTO adoption_items VALUES(?,?)",
            (
                (adoption_id, item_ids[item])
                for item in row.item_event_ids
                if item in item_ids
            ),
        )


def _stable_ids(records, mapping: dict[str, int | str]) -> dict[str, int]:
    next_id = max((int(value) for value in mapping.values()), default=0)
    result = {}
    for record in records:
        if record.event_id not in mapping:
            next_id += 1
            mapping[record.event_id] = next_id
        result[record.event_id] = int(mapping[record.event_id])
    return result


def _read_id_map(
    connection: sqlite3.Connection, logged_ids: set[str]
) -> dict[str, dict[str, int | str]]:
    row = connection.execute("SELECT value FROM meta WHERE key='log_map'").fetchone()
    if row:
        try:
            loaded = json.loads(row[0])
            if isinstance(loaded, dict) and set(loaded.get("items", {})) <= logged_ids:
                return loaded
        except ValueError, TypeError:
            pass
    recovery_path = Path(
        f"{connection.execute('PRAGMA database_list').fetchone()[2]}"
        f"{PRE_LOG_SUFFIX}.map"
    )
    try:
        loaded = json.loads(recovery_path.read_text())
        if isinstance(loaded, dict) and set(loaded.get("items", {})) <= logged_ids:
            return loaded
    except OSError, ValueError, TypeError:
        pass
    return {}


def _write_map(path: Path, mapping: dict[str, dict[str, int | str]]) -> None:
    with path.open("w") as handle:
        json.dump(mapping, handle, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())


def _write_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) "
        "DO UPDATE SET value=excluded.value",
        (key, value),
    )


def bump_timestamp(value: str) -> str:
    if (
        len(value) != 24
        or value[4] != "-"
        or value[7] != "-"
        or value[10] != "T"
        or value[13] != ":"
        or value[16] != ":"
        or value[19] != "."
        or value[23] != "Z"
        or any(not (c.isascii() and (c.isdigit() or c in "-T:.")) for c in value[:23])
    ):
        return value + "~"
    import datetime

    parsed = datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    return (parsed + datetime.timedelta(milliseconds=1)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:23] + "Z"


def next_dump_ts(previous: str, at: str) -> str:
    return at if at > previous else bump_timestamp(previous)
