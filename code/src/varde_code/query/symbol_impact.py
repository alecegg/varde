"""Reverse symbol traversal over resolved calls and inheritance edges."""

from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from varde_code.model import EdgeKind, EntityKind

from .params import QueryError, req_str
from .simple import _db, _matches_path

_DECLARATIONS = {
    EntityKind.FUNCTION,
    EntityKind.CLASS,
    EntityKind.INTERFACE,
    EntityKind.VARIABLE,
    EntityKind.PARAMETER,
}


@dataclass(frozen=True)
class _Node:
    id: int
    file: int
    path: str
    kind: EntityKind | None
    name: str
    start: int
    end: int


def _nodes(conn: sqlite3.Connection) -> dict[int, _Node]:
    rows = conn.execute(
        """SELECT e.id,e.file_id,f.path,e.kind,e.name,e.start_byte,e.end_byte
        FROM entities e JOIN files f ON f.id=e.file_id
        WHERE e.kind IN (0,1,2,3,4,5,6,19)"""
    )
    return {
        row[0]: _Node(
            row[0], row[1], row[2], EntityKind.from_i64(row[3]), row[4], row[5], row[6]
        )
        for row in rows
    }


def _seed(input: dict[str, Any], nodes: dict[int, _Node]) -> _Node:
    name = req_str(input, "name")
    file_path = input.get("filePath")
    kind_name = input.get("kind")
    for field, value in (("filePath", file_path), ("kind", kind_name)):
        if value is not None and not isinstance(value, str):
            raise QueryError("invalid_input", f"{field} must be a string")
    kind = None
    if kind_name is not None:
        kind = next(
            (item for item in _DECLARATIONS if item.as_str() == kind_name), None
        )
        if kind is None:
            raise QueryError(
                "invalid_input", f"{kind_name!r} is not a declaration kind"
            )
    matches = [
        node
        for node in nodes.values()
        if node.kind in _DECLARATIONS
        and node.name == name
        and (kind is None or node.kind == kind)
        and (file_path is None or _matches_path(node.path, file_path))
    ]
    if not matches:
        raise QueryError("not_found", f"declaration {name!r}")
    if len(matches) > 1:
        raise QueryError(
            "ambiguous_symbol",
            (
                f"multiple declarations match {name!r}; narrow filePath or kind "
                "(same-file overloads remain ambiguous)"
            ),
        )
    return matches[0]


def _canonical_targets(nodes: dict[int, _Node]) -> dict[int, int]:
    declarations: dict[tuple[int, str], list[_Node]] = defaultdict(list)
    targets = {}
    for node in nodes.values():
        if node.kind in _DECLARATIONS:
            declarations[(node.file, node.name)].append(node)
            targets[node.id] = node.id
    for wrapper in (node for node in nodes.values() if node.kind == EntityKind.EXPORT):
        contained = [
            node
            for node in declarations.get((wrapper.file, wrapper.name), ())
            if wrapper.start <= node.start and wrapper.end >= node.end
        ]
        if len(contained) == 1:
            targets[wrapper.id] = contained[0].id
    return targets


def _call_owner(site: _Node, callables: dict[int, list[_Node]]) -> int | None:
    enclosing = sorted(
        (
            node
            for node in callables.get(site.file, ())
            if node.start <= site.start
            and node.end >= site.end
            and node.end > node.start
        ),
        key=lambda node: node.end - node.start,
    )
    if not enclosing:
        return None
    nearest = enclosing[0]
    if nearest.kind == EntityKind.CALLABLE_BOUNDARY:
        return None
    if (
        len(enclosing) > 1
        and enclosing[1].end - enclosing[1].start == nearest.end - nearest.start
    ):
        return None
    return nearest.id


def _reverse_edges(
    conn: sqlite3.Connection, nodes: dict[int, _Node]
) -> tuple[dict[int, list[tuple[int, int | None]]], int]:
    callables: dict[int, list[_Node]] = defaultdict(list)
    for node in nodes.values():
        if node.kind in {EntityKind.FUNCTION, EntityKind.CALLABLE_BOUNDARY}:
            callables[node.file].append(node)
    targets = _canonical_targets(nodes)
    reverse: dict[int, list[tuple[int, int | None]]] = defaultdict(list)
    unresolved = 0
    for file_id, source_id, target_id, kind, resolved in conn.execute(
        "SELECT from_file_id,from_entity_id,to_entity_id,kind,resolved "
        "FROM resolved_edges WHERE kind IN (0,2,3)"
    ):
        target = targets.get(target_id) if resolved and target_id is not None else None
        if target is None:
            unresolved += 1
            continue
        source = nodes.get(source_id) if source_id is not None else None
        owner = None
        if source is not None:
            if source.kind in _DECLARATIONS:
                owner = source.id
            elif kind == EdgeKind.CALL.as_i64():
                owner = _call_owner(source, callables)
        reverse[target].append((file_id, owner))
    return reverse, unresolved


def run(input: dict[str, Any]) -> dict[str, Any]:
    conn = _db(input)
    try:
        nodes = _nodes(conn)
        seed = _seed(input, nodes)
        reverse, unresolved = _reverse_edges(conn, nodes)
        visited = {seed.id}
        affected: set[int] = set()
        unmapped = 0
        queue = deque([seed.id])
        while queue:
            target = queue.popleft()
            for file_id, owner in reverse.get(target, ()):
                if owner == seed.id:
                    continue
                affected.add(file_id)
                if owner is None:
                    unmapped += 1
                elif owner not in visited:
                    visited.add(owner)
                    queue.append(owner)
        paths = (
            [
                row[0]
                for row in conn.execute(
                    "SELECT path FROM files WHERE id IN ({}) ORDER BY path".format(  # noqa: S608 - Only the generated placeholder count is interpolated.
                        ",".join("?" for _ in affected)
                    ),
                    tuple(affected),
                )
            ]
            if affected
            else []
        )
        return {
            "declaring_file": seed.path,
            "blast_radius": paths,
            "analysis": {
                "status": "partial",
                "basis": "resolved_calls_and_inheritance",
                "unresolved_edges": unresolved,
                "unmapped_owners": unmapped,
                "limitations": [
                    (
                        "Arbitrary data references and dynamic dispatch are not fully "
                        "indexed; empty impact does not prove isolation."
                    ),
                    (
                        "Calls without a unique named callable owner, including "
                        "anonymous callbacks, report their file but stop symbol "
                        "propagation."
                    ),
                ],
            },
        }
    finally:
        conn.close()
