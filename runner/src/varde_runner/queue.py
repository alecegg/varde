"""Pure queue rules; the saved ordering lives in `varde_data.queue_order`."""

from __future__ import annotations

import re
from typing import Any

from varde_data.queue_order import (
    has_saved_order,
    move_order,
    move_plan,
    ordered_ids,
    read_order,
)

CATEGORY_LIMITS = {"new-feature": 2, "fixes": 1, "friction": 1}
UNCATEGORIZED = "uncategorized"


def category_for_plan(plan_id: str, frontmatter_category: str | None = None) -> str:
    if frontmatter_category is not None:
        if frontmatter_category not in CATEGORY_LIMITS:
            raise ValueError(f"unknown plan category: {frontmatter_category}")
        return frontmatter_category
    if plan_id.startswith("friction-"):
        return "friction"
    if plan_id.startswith("fix"):
        return "fixes"
    return UNCATEGORIZED


def next_up(plan_ids: list[str]) -> str | None:
    return plan_ids[0] if plan_ids else None


def slot_usage(
    running_ids: list[str], category_ids: set[str], limit: int
) -> dict[str, int]:
    return {
        "used": sum(plan_id in category_ids for plan_id in running_ids),
        "limit": limit,
    }


def flatten_plans(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return rows
    for row in value:
        if isinstance(row, dict):
            rows.append(row)
            rows.extend(flatten_plans(row.get("children", [])))
    return rows


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip().strip("'\"")
    return fields


def task_acceptance(text: str) -> list[str]:
    match = re.search(
        r"(?im)^##?\s+Acceptance criteria\s*$([\s\S]*?)(?=^##?\s|\Z)", text
    )
    if not match:
        return []
    return [
        line.strip().lstrip("- ")
        for line in match.group(1).splitlines()
        if line.strip().startswith(("-", "*"))
    ]


__all__ = [
    "CATEGORY_LIMITS",
    "UNCATEGORIZED",
    "category_for_plan",
    "flatten_plans",
    "has_saved_order",
    "move_order",
    "move_plan",
    "next_up",
    "ordered_ids",
    "parse_frontmatter",
    "read_order",
    "slot_usage",
    "task_acceptance",
]
