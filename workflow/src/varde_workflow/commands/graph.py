"""Workflow graph command behavior."""

from __future__ import annotations

from typing import Any

from varde_workflow.graph import ArtifactGraph
from varde_workflow.output import page_bounds, pagination_meta
from varde_workflow.schema import WorkflowSchema


def graph_data(
    path: str, *, offset: int = 0, limit: int = 100, all_items: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    schema = WorkflowSchema.resolve(path)
    data = ArtifactGraph.resolve(path, schema).to_json(schema)
    meta = paginate_graph(data, offset=offset, limit=limit, all_items=all_items)
    return data, meta


def paginate_graph(
    data: dict[str, Any], *, offset: int, limit: int, all_items: bool = False
) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    truncated = False
    for key in ("nodes", "edges", "blockers"):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        total = len(items)
        start, end = page_bounds(total, offset, limit, all_items)
        data[key] = items[start:end]
        truncated |= end < total
        sections[key] = pagination_meta(total, start, end, limit, all_items)[
            "pagination"
        ]
    return {"truncated": truncated, "pagination": {"sections": sections}}
