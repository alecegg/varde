"""Block type for phases and milestones: timeline."""

from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    str_field,
    tables,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec

ORIENTATIONS = ("vertical", "horizontal")
STATUSES = ("done", "active", "planned", "blocked")
MAX_VERTICAL = 200
MAX_HORIZONTAL = 24
ITEM_OPTIONAL = {"note", "owner"}


def _item_faults(item: dict[str, object], where: str) -> list[Fault]:
    faults = check_keys(item, {"when", "label", "status"}, ITEM_OPTIONAL, where)
    for key in ("when", "label", "note", "owner"):
        faults += str_field(item, key, where)
    if "status" in item and item["status"] not in STATUSES:
        faults.append(
            Fault("type", f"{where}: status must be one of {', '.join(STATUSES)}")
        )
    return faults


def _limit_fault(count: int, horizontal: bool) -> list[Fault]:
    cap = MAX_HORIZONTAL if horizontal else MAX_VERTICAL
    if count <= cap:
        return []
    layout = "horizontal" if horizontal else "vertical"
    return [Fault("limit", f"timeline: at most {cap} items when {layout}; split it")]


def _orientation_faults(data: dict[str, object]) -> list[Fault]:
    if "orientation" not in data or data["orientation"] in ORIENTATIONS:
        return []
    return [Fault("type", "timeline: orientation must be vertical or horizontal")]


def _items_faults(data: dict[str, object]) -> list[Fault]:
    items = data["item"]
    if not isinstance(items, list) or not items:
        return [Fault("type", "timeline: 'item' must be a non-empty list of tables")]
    if not all(isinstance(i, dict) for i in items):
        return [Fault("type", "timeline: 'item' must be a list of tables")]
    faults = _limit_fault(len(items), data.get("orientation") == "horizontal")
    for n, item in enumerate(tables(data, "item", "timeline"), 1):
        faults += _item_faults(item, f"timeline: item[{n}]")
    return faults


def validate_timeline(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"item"}, {"title", "orientation"}, "timeline")
    faults += str_field(data, "title", "timeline") + _orientation_faults(data)
    return faults + (_items_faults(data) if "item" in data else [])


TIMELINE = BlockSpec(
    "timeline",
    "Phases and milestones in order, each with a status",
    (
        "title        optional caption",
        "orientation  vertical (default) or horizontal; horizontal is a row on",
        "             wide pages (at most 24 items, scrolls if it does not fit) and",
        "             a vertical list on narrow ones",
        "item         list of {when, label, status, note, owner}; when is free",
        "             text (a date or a phase name); status is done, active,",
        "             planned or blocked; at most 200 items (24 horizontal)",
        "  Status is a glyph plus a word, never colour alone; the first active",
        "  item is marked as the current step.",
    ),
    r"""timeline = timeline(
  title: "Rollout",
  item: [
    {"when": "Week 1", "label": "Design review", "status": "done"},
    {"when": "Week 2", "label": "Build", "status": "active", "owner": "Platform"},
    {"when": "Week 4", "label": "Launch", "status": "planned",
     "note": "Needs sign-off."},
  ],
)
""",
    validate_timeline,
)
