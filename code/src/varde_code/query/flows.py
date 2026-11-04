"""Build full reachable call trees for semantic entrypoints."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from varde_code.model import EdgeKind

from .entrypoints import Entrypoint
from .noise_filter import is_generated_or_vendored_path
from .params import QueryError

MAX_FLOW_DEPTH = 1000


@dataclass(frozen=True)
class Backref:
    entrypoint: str
    file: str
    symbol: str
    entity_id: int


@dataclass
class FlowNode:
    entity_id: int
    file: str
    symbol: str
    children: list[FlowNode] = field(default_factory=list)
    backref_to: Backref | None = None

    def to_json(self) -> dict[str, object]:
        node: dict[str, object] = {
            "entity_id": self.entity_id,
            "file": self.file,
            "symbol": self.symbol,
        }
        if self.backref_to is not None:
            ref = self.backref_to
            node["backref_to"] = {
                "entrypoint": ref.entrypoint,
                "file": ref.file,
                "symbol": ref.symbol,
                "entity_id": ref.entity_id,
            }
        else:
            node["children"] = [child.to_json() for child in self.children]
        return node


@dataclass(frozen=True)
class FlowTree:
    entrypoint: str
    root: FlowNode

    def to_json(self) -> dict[str, object]:
        return {"entrypoint": self.entrypoint, "root": self.root.to_json()}


def build_flows(
    conn: sqlite3.Connection, entrypoints: list[Entrypoint]
) -> list[FlowTree]:
    try:
        entities: dict[int, tuple[int, str | None, str, str]] = {
            row[0]: (row[1], row[2], row[3], row[4])
            for row in conn.execute(
                """SELECT e.id, e.file_id, e.owner_type, e.name, f.path
                   FROM entities e JOIN files f ON f.id=e.file_id"""
            )
        }
        # The key records the call site's file, owner type and enclosing function.
        callees: dict[tuple[int, str | None, str], list[int]] = {}
        for file_id, owner, enclosing, target in conn.execute(
            """SELECT call_e.file_id, call_e.owner_type, call_e.enclosing_function,
                      re.to_entity_id
               FROM resolved_edges re JOIN entities call_e
                   ON call_e.id=re.from_entity_id
               WHERE re.kind=? AND re.resolved=1 AND re.to_entity_id IS NOT NULL
               ORDER BY re.id""",
            (EdgeKind.CALL.as_i64(),),
        ):
            if enclosing is not None:
                callees.setdefault((file_id, owner, enclosing), []).append(target)
    except sqlite3.Error as exc:
        raise QueryError("db_error", str(exc)) from exc

    rendered: dict[int, Backref] = {}

    def expand(entity_id: int, entrypoint: str, path: set[int], depth: int) -> FlowNode:
        try:
            file, symbol = entities[entity_id][3], entities[entity_id][2]
        except KeyError as exc:
            raise QueryError("not_found", f"entity {entity_id}") from exc
        path.add(entity_id)
        children: list[FlowNode] = []
        file_id, owner, _name, _file = entities[entity_id]
        for callee_id in callees.get((file_id, owner, symbol), []):
            if callee_id in path:
                continue
            try:
                callee_file, callee_symbol = (
                    entities[callee_id][3],
                    entities[callee_id][2],
                )
            except KeyError as exc:
                raise QueryError("not_found", f"entity {callee_id}") from exc
            if is_generated_or_vendored_path(callee_file):
                continue
            if callee_id in rendered:
                ref = rendered[callee_id]
                children.append(
                    FlowNode(
                        callee_id,
                        callee_file,
                        callee_symbol,
                        backref_to=Backref(
                            ref.entrypoint, ref.file, ref.symbol, callee_id
                        ),
                    )
                )
                continue
            rendered[callee_id] = Backref(
                entrypoint, callee_file, callee_symbol, callee_id
            )
            if depth + 1 >= MAX_FLOW_DEPTH:
                children.append(FlowNode(callee_id, callee_file, callee_symbol))
            else:
                children.append(expand(callee_id, entrypoint, path, depth + 1))
        path.remove(entity_id)
        return FlowNode(entity_id, file, symbol, children)

    trees = []
    for item in entrypoints:
        rendered[item.entity_id] = Backref(
            item.symbol, item.file, item.symbol, item.entity_id
        )
        trees.append(
            FlowTree(item.symbol, expand(item.entity_id, item.symbol, set(), 0))
        )
    return trees
