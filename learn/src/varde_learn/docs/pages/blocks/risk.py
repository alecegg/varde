"""Block type for a risk matrix: likelihood by impact with a mitigation list."""

from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    duplicates,
    str_field,
    tables,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec

LEVELS = ("low", "medium", "high")
MAX_ITEMS = 200
ITEM_OPTIONAL = {"mitigation", "owner"}


def _item_faults(item: dict[str, object], where: str) -> list[Fault]:
    required = {"id", "label", "likelihood", "impact"}
    faults = check_keys(item, required, ITEM_OPTIONAL, where)
    for key in ("id", "label", "mitigation", "owner"):
        faults += str_field(item, key, where)
    for key in ("likelihood", "impact"):
        if key in item and item[key] not in LEVELS:
            faults.append(
                Fault("type", f"{where}: {key} must be one of {', '.join(LEVELS)}")
            )
    return faults


def _unique_id_faults(items: list[dict[str, object]]) -> list[Fault]:
    ids = [i for r in items if isinstance(i := r.get("id"), str)]
    return [Fault("duplicate-id", f"risk: duplicate id '{d}'") for d in duplicates(ids)]


def _items_faults(data: dict[str, object]) -> list[Fault]:
    items = data["item"]
    if not isinstance(items, list) or not items:
        return [Fault("type", "risk: 'item' must be a non-empty list of tables")]
    if not all(isinstance(i, dict) for i in items):
        return [Fault("type", "risk: 'item' must be a list of tables")]
    faults: list[Fault] = []
    if len(items) > MAX_ITEMS:
        faults.append(Fault("limit", f"risk: at most {MAX_ITEMS} items; split it"))
    rows = tables(data, "item", "risk")
    for n, item in enumerate(rows, 1):
        faults += _item_faults(item, f"risk: item[{n}]")
    return faults + _unique_id_faults(rows)


def validate_risk(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"item"}, {"title"}, "risk")
    faults += str_field(data, "title", "risk")
    return faults + (_items_faults(data) if "item" in data else [])


RISK = BlockSpec(
    "risks",
    "Risks placed by likelihood and impact, with severity and mitigations",
    (
        "title        optional caption",
        "item         list of {id, label, likelihood, impact, mitigation, owner};",
        "             likelihood and impact are low, medium or high; ids are",
        "             unique; at most 200 items",
        "  Severity is likelihood x impact (low=1, medium=2, high=3): 1-2 low,",
        "  3-4 medium, 6 high, 9 critical. It is shown as a glyph and a word.",
        "  The 3x3 grid is a summary; the full list below it carries every",
        "  risk. A grid cell shows at most 4 ids and then '+N'.",
    ),
    r"""risks = risks(
  title: "Launch risks",
  item: [
    {"id": "R1", "label": "Vendor patch slips", "likelihood": "high", "impact": "high",
     "mitigation": "Ship behind a flag.", "owner": "Platform"},
    {"id": "R2", "label": "Docs lag", "likelihood": "medium", "impact": "low"},
  ],
)
""",
    validate_risk,
)
