"""Block type for a headline strip of numbers: stats."""

from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    is_number,
    str_field,
    tables,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec

DIRECTIONS = ("up", "down", "flat")
GOODS = ("up", "down")
TONES = ("neutral", "info", "decision", "risk", "warning", "success")
MIN_ITEMS = 2
MAX_ITEMS = 6
MAX_DECIMALS = 6
SIGNS = ("+", "-", "−")
ITEM_OPTIONAL = {"delta", "direction", "good", "tone", "note", "decimals"}


def delta_direction(item: dict[str, object]) -> str | None:
    """The stated direction, else the sign of the delta; None when neither says."""
    direction = item.get("direction")
    if isinstance(direction, str):
        return direction
    delta = item.get("delta")
    if is_number(delta):
        return "flat" if delta == 0 else "up" if delta > 0 else "down"  # type: ignore[operator]
    if isinstance(delta, str) and delta.strip()[:1] == "+":
        return "up"
    if isinstance(delta, str) and delta.strip()[:1] in SIGNS[1:]:
        return "down"
    return None


def _scalar_fault(item: dict[str, object], key: str, where: str) -> list[Fault]:
    if key not in item or is_number(item[key]):
        return []
    return str_field(item, key, where)


def _choice_fault(
    item: dict[str, object], key: str, allowed: tuple[str, ...], where: str
) -> list[Fault]:
    if key not in item or item[key] in allowed:
        return []
    return [Fault("type", f"{where}: {key} must be one of {', '.join(allowed)}")]


def _is_places(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value in range(MAX_DECIMALS + 1)
    )


def _decimals_fault(item: dict[str, object], where: str) -> list[Fault]:
    if "decimals" not in item or _is_places(item["decimals"]):
        return []
    return [Fault("type", f"{where}: decimals must be 0 to {MAX_DECIMALS}")]


def _delta_fault(item: dict[str, object], where: str) -> list[Fault]:
    if "delta" not in item:
        return []
    if not str(item["delta"]).strip():
        return [Fault("type", f"{where}: 'delta' must be a non-empty string or number")]
    if delta_direction(item) is None:
        return [Fault("direction", f"{where}: delta needs a direction or a +/- sign")]
    return []


def _item_faults(item: dict[str, object], where: str) -> list[Fault]:
    faults = check_keys(item, {"label", "value"}, ITEM_OPTIONAL, where)
    faults += str_field(item, "label", where) + str_field(item, "note", where)
    faults += _scalar_fault(item, "value", where) + _decimals_fault(item, where)
    faults += _choice_fault(item, "direction", DIRECTIONS, where)
    faults += _choice_fault(item, "good", GOODS, where)
    faults += _choice_fault(item, "tone", TONES, where)
    if "delta" in item and not (
        is_number(item["delta"]) or isinstance(item["delta"], str)
    ):
        return faults + [Fault("type", f"{where}: 'delta' must be a string or number")]
    return faults + _delta_fault(item, where)


def _items_faults(data: dict[str, object]) -> list[Fault]:
    items = data["item"]
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        return [Fault("type", "stats: 'item' must be a list of tables")]
    faults: list[Fault] = []
    if not MIN_ITEMS <= len(items) <= MAX_ITEMS:
        faults.append(
            Fault("limit", f"stats: {MIN_ITEMS} to {MAX_ITEMS} items; split the block")
        )
    for n, item in enumerate(tables(data, "item", "stats"), 1):
        faults += _item_faults(item, f"stats: item[{n}]")
    return faults


def validate_stats(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"item"}, set(), "stats")
    return faults + (_items_faults(data) if "item" in data else [])


STATS = BlockSpec(
    "stats",
    "A strip of 2 to 6 headline numbers with an optional change",
    (
        "item   list of {label, value, delta, direction, good, tone, note, decimals},",
        "       2 to 6; value is text or a number (numbers get thousands separators;",
        "       decimals sets the places); delta is text or a number, shown as",
        "       'up 12%' with an arrow; direction is up, down or flat (else the",
        "       sign of delta); good says which direction is good (up or down), so",
        "       a good move reads green and a bad one red; flat is neutral;",
        "       tone overrides: neutral, info, decision, risk, warning or success",
        "  The word up, down or flat is always in the text, never colour alone.",
    ),
    r"""stats = stats(
  item: [
    {"label": "Requests", "value": 1204331, "delta": "12%", "good": "up",
     "direction": "up"},
    {"label": "p95 latency", "value": "212 ms", "delta": "-8%", "good": "down"},
    {"label": "Error rate", "value": 0.4, "decimals": 2, "delta": "0.1 pt",
     "direction": "up", "good": "down"},
  ],
)
""",
    validate_stats,
)
