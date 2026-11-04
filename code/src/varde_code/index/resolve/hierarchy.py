"""Resolve type hierarchy entities into graph edges."""

from collections.abc import Mapping, Sequence
from typing import Any

from varde_code.model import EdgeKind, EntityKind

_HIERARCHY_OWNERS = {EntityKind.CLASS, EntityKind.INTERFACE}


def resolve_hierarchy(
    entities: Sequence[Mapping[str, Any]],
) -> list[dict[str, object]]:
    """Resolve extends and implements entities to uniquely named types."""
    targets: dict[str, int | None] = {}
    owners: dict[tuple[int, str], int] = {}
    for entity_id, entity in enumerate(entities):
        kind = entity["kind"]
        name = str(entity["name"])
        file_id = int(entity["file_id"])
        if kind in _HIERARCHY_OWNERS:
            if name in targets:
                targets[name] = None
            else:
                targets[name] = entity_id
            owners.setdefault((file_id, name), entity_id)

    edges = []
    for _entity_id, entity in enumerate(entities):
        kind = entity["kind"]
        if kind == EntityKind.EXTENDS:
            edge_kind = EdgeKind.EXTENDS
        elif kind == EntityKind.IMPLEMENTS:
            edge_kind = EdgeKind.IMPLEMENTS
        else:
            continue

        name = str(entity["name"])
        file_id = int(entity["file_id"])
        owner_name = entity.get("enclosing_function")
        from_entity = (
            owners.get((file_id, owner_name)) if isinstance(owner_name, str) else None
        )
        target_id = targets.get(name)
        target = {"target": "unknown"}
        if target_id is not None:
            target = {"target": "entity", "id": target_id}
        edges.append(
            {
                "from": file_id,
                "to": target,
                "kind": edge_kind.as_str(),
                "resolved": target_id is not None,
                "from_entity": from_entity,
            }
        )
    return edges
