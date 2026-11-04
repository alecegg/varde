"""Block type for a static checklist with progress: checklist."""

from varde_learn.docs.pages.blocks.rules import Fault, check_keys, str_field, tables
from varde_learn.docs.pages.blocks.spec import BlockSpec

STATUSES = ("done", "open", "blocked")
MAX_ITEMS = 500
ITEM_OPTIONAL = {"id", "checked", "note", "status"}


def _agree_faults(item: dict[str, object], where: str) -> list[Fault]:
    status = item.get("status")
    checked = item.get("checked")
    if status not in STATUSES or not isinstance(checked, bool):
        return []
    if checked == (status == "done"):
        return []
    return [Fault("conflict", f"{where}: checked and status disagree")]


def _item_faults(item: dict[str, object], where: str) -> list[Fault]:
    faults = check_keys(item, {"label"}, ITEM_OPTIONAL, where)
    for key in ("label", "id", "note"):
        faults += str_field(item, key, where)
    if "checked" in item and not isinstance(item["checked"], bool):
        faults.append(Fault("type", f"{where}: 'checked' must be true or false"))
    if "status" in item and item["status"] not in STATUSES:
        faults.append(Fault("type", f"{where}: status must be done, open or blocked"))
    return faults + _agree_faults(item, where)


def _items_faults(data: dict[str, object]) -> list[Fault]:
    items = data["items"]
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        return [Fault("type", "checklist: 'items' must be a list of tables")]
    faults: list[Fault] = []
    if len(items) > MAX_ITEMS:
        faults.append(Fault("limit", f"checklist: at most {MAX_ITEMS} items"))
    for n, item in enumerate(tables(data, "items", "checklist"), 1):
        faults += _item_faults(item, f"checklist: items[{n}]")
    return faults


def validate_checklist(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"items"}, {"title"}, "checklist")
    faults += str_field(data, "title", "checklist")
    return faults + (_items_faults(data) if "items" in data else [])


CHECKLIST = BlockSpec(
    "checklist",
    "A static checklist with a state word per item and a progress count",
    (
        "title  optional heading",
        "items  list of {label, id, checked, note, status}, up to 500; label is",
        "       plain text with `code` spans; note shows muted under the label",
        "       status is done, open (default) or blocked; checked: true means done",
        "       and must agree with status",
        "  Shows the count as 'N of M done' beside a progress bar. Not interactive.",
    ),
    r"""checklist = checklist(
  title: "Acceptance",
  items: [
    {"label": "Queue keeps order", "status": "done"},
    {"label": "Retry uses `backoff`", "note": "API spec", "status": "blocked"},
    {"label": "Docs updated"},
  ],
)
""",
    validate_checklist,
)
