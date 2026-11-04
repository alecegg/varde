"""Persist resolved edges and reconstruct their flat resolver representation."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from varde_code.model import EdgeKind


@dataclass
class PersistedState:
    """Resolver state paired with the SQLite IDs for its flattened rows."""

    entities: Sequence[Mapping[str, object]]
    entity_ids: list[int]
    files: list[str]
    file_ids: list[int]
    file_index: dict[int, int]


def resolved_edge_rows(
    state: PersistedState, edges: Sequence[Mapping[str, object]]
) -> list[tuple[int, int | None, int, int, int | None, int | None]]:
    rows = []
    for edge in edges:
        source = _index(edge.get("from"), len(state.file_ids), "source file")
        kind = _edge_kind(edge.get("kind"))
        resolved = bool(edge.get("resolved"))
        source_entity = _optional_index(edge.get("from_entity"), len(state.entity_ids))
        target = edge.get("to")
        if not isinstance(target, Mapping):
            raise ValueError("edge target must be an object")
        target_file = target_entity = None
        if resolved:
            target_id = _index(
                target.get("id"),
                len(state.file_ids)
                if target.get("target") == "file"
                else len(state.entities),
                "target",
            )
            if target.get("target") == "file":
                target_file = state.file_ids[target_id]
            elif target.get("target") == "entity":
                target_entity = state.entity_ids[target_id]
                entity_file = state.entities[target_id].get("file_id")
                target_file = state.file_ids[
                    _index(entity_file, len(state.file_ids), "target entity file")
                ]
            else:
                raise ValueError("resolved edge target must be a file or entity")
        rows.append(
            (
                state.file_ids[source],
                target_file,
                kind.as_i64(),
                int(resolved),
                _db_entity_id(state, source_entity),
                target_entity,
            )
        )
    return rows


def rewrite_edges(
    connection: sqlite3.Connection,
    state: PersistedState,
    edges: Sequence[Mapping[str, object]],
    nodes: Sequence[Mapping[str, object]],
) -> None:
    """Reconcile persisted edge rows, denormalized fan counts, and edge revisions."""
    if len(nodes) != len(state.file_ids):
        raise ValueError("resolved graph nodes must match persisted files")
    rows = resolved_edge_rows(state, edges)
    with connection:
        write_edge_diff(connection, state.file_ids, rows)
        for file_id, node in zip(state.file_ids, nodes, strict=True):
            connection.execute(
                "UPDATE files SET fan_in = ?, fan_out = ? WHERE id = ?",
                (
                    _integer_value(node["fan_in"]),
                    _integer_value(node["fan_out"]),
                    file_id,
                ),
            )
        connection.execute("UPDATE files SET edges_built_rev = rev")


def rewrite_import_edges(
    connection: sqlite3.Connection,
    state: PersistedState,
    edges: Sequence[Mapping[str, object]],
) -> None:
    """Replace import rows while preserving other edge kinds."""
    rows = [
        row for row in resolved_edge_rows(state, edges) if row[2] == EdgeKind.IMPORT
    ]
    with connection:
        connection.execute(
            "DELETE FROM resolved_edges WHERE kind = ?", (EdgeKind.IMPORT.as_i64(),)
        )
        _insert_edge_rows(connection, rows)


def write_edge_diff(
    connection: sqlite3.Connection,
    file_ids: Sequence[int],
    rows: Sequence[tuple[int, int | None, int, int, int | None, int | None]],
) -> None:
    """Keep matching edge row IDs and replace only changed rows for source files."""
    if not file_ids:
        return
    old: dict[tuple[object, ...], list[int]] = defaultdict(list)
    for start in range(0, len(file_ids), 400):
        chunk = file_ids[start : start + 400]
        marks = ",".join("?" for _ in chunk)
        for edge_id, *row in connection.execute(
            f"SELECT id, from_file_id, to_file_id, kind, resolved, from_entity_id, to_entity_id "
            f"FROM resolved_edges WHERE from_file_id IN ({marks}) ORDER BY id",
            chunk,
        ):
            old[tuple(row)].append(edge_id)
    inserts = []
    for row in rows:
        matches = old.get(tuple(row))
        if matches:
            matches.pop()
        else:
            inserts.append(row)
    for ids in old.values():
        connection.executemany(
            "DELETE FROM resolved_edges WHERE id = ?", ((edge_id,) for edge_id in ids)
        )
    _insert_edge_rows(connection, inserts)


def _insert_edge_rows(
    connection: sqlite3.Connection, rows: Sequence[tuple[object, ...]]
) -> None:
    connection.executemany(
        "INSERT INTO resolved_edges "
        "(from_file_id,to_file_id,kind,resolved,from_entity_id,to_entity_id) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )


def _db_entity_id(state: PersistedState, index: int | None) -> int | None:
    return None if index is None else state.entity_ids[index]


def _edge_kind(value: object) -> EdgeKind:
    if isinstance(value, str):
        try:
            return EdgeKind[value.upper()]
        except KeyError as exc:
            raise ValueError(f"unknown edge kind: {value}") from exc
    if isinstance(value, int):
        kind = EdgeKind.from_i64(value)
        if kind is not None:
            return kind
    raise ValueError(f"unknown edge kind: {value}")


def _integer_value(value: object) -> int:
    if not isinstance(value, (int, str, float, bytes, bytearray)):
        raise TypeError(
            "int() argument must be a string, a bytes-like object or a real number"
        )
    return int(value)


def _index(value: object, length: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < length:
        raise ValueError(f"{label} index is out of range")
    return value


def _optional_index(value: object, length: int) -> int | None:
    return None if value is None else _index(value, length, "entity")
