"""Block types that hold other blocks by id: tabs and columns.

Each prop list names panels `{label, blocks: [id, ...]}`; an id names another
statement of the same document. The per-statement validators check shape; the
document-level `container_errors` checks the ids against the whole page.
"""

import re
from collections.abc import Sequence

from varde_learn.docs.pages.blocks.rules import Fault, check_keys, str_field, tables
from varde_learn.docs.pages.blocks.spec import BlockSpec

MAX_PANELS = {"tabs": 12, "columns": 4}
MAX_HELD = 200
HOLD_KEYS = {"tabs": "tab", "columns": "col"}
CONTAINERS = frozenset(HOLD_KEYS)
# Components whose inputs must stay visible, so a tab cannot hide them.
INPUT_COMPONENTS = frozenset(
    {"choice", "form", "comment", "ranking", "slider", "decision"}
)
HELD_ID = re.compile(r"^[a-z][a-z0-9-]{0,47}$")


def _panel_faults(
    panel: dict[str, object], where: str, label_needed: bool
) -> list[Fault]:
    faults = check_keys(
        panel, {"blocks"} | ({"label"} if label_needed else set()), {"label"}, where
    )
    faults += str_field(panel, "label", where)
    held = panel.get("blocks")
    if "blocks" not in panel:
        return faults
    if not isinstance(held, list) or not held:
        return faults + [
            Fault("type", f"{where}: 'blocks' must be a non-empty list of ids")
        ]
    bad = [h for h in held if not (isinstance(h, str) and HELD_ID.match(h))]
    if bad:
        faults.append(
            Fault("type", f"{where}: block ids are lowercase words like 'my-block'")
        )
    return faults


def _validate(data: dict[str, object], kind: str) -> list[Fault]:
    key = HOLD_KEYS[kind]
    faults = check_keys(data, {key}, set(), kind)
    if key not in data:
        return faults
    panels = data[key]
    if (
        not isinstance(panels, list)
        or not panels
        or not all(isinstance(p, dict) for p in panels)
    ):
        return faults + [
            Fault("type", f"{kind}: '{key}' must be a non-empty list of tables")
        ]
    if len(panels) > MAX_PANELS[kind]:
        faults.append(Fault("limit", f"{kind}: at most {MAX_PANELS[kind]} entries"))
    total = 0
    for n, panel in enumerate(tables(data, key, kind), 1):
        faults += _panel_faults(panel, f"{kind}: {key}[{n}]", kind == "tabs")
        held = panel.get("blocks")
        total += len(held) if isinstance(held, list) else 0
    if total > MAX_HELD:
        faults.append(Fault("limit", f"{kind}: at most {MAX_HELD} held blocks"))
    return faults


def validate_tabs(data: dict[str, object]) -> list[Fault]:
    return _validate(data, "tabs")


def validate_columns(data: dict[str, object]) -> list[Fault]:
    return _validate(data, "columns")


def held_ids(kind: str, props: dict[str, object]) -> list[str]:
    """Every held id of one container's props, in panel order (valid shapes only)."""
    panels = props.get(HOLD_KEYS[kind])
    if not isinstance(panels, list):
        return []
    out: list[str] = []
    for panel in panels:
        held = panel.get("blocks") if isinstance(panel, dict) else None
        out += [h for h in held if isinstance(h, str)] if isinstance(held, list) else []
    return out


# (line, component, id, props) of each statement, in document order.
Statements = Sequence[tuple[int, str, str, dict[str, object]]]


def _chain_back(start: str, target: str, holds: dict[str, list[str]]) -> bool:
    """Whether `start` holds `target`, directly or through held containers."""
    seen: set[str] = set()
    todo = [start]
    while todo:
        node = todo.pop()
        if node == target:
            return True
        if node not in seen:
            seen.add(node)
            todo += holds.get(node, [])
    return False


def _held_fault(kind: str, own: str, held: str, component: str | None) -> Fault | None:
    if component is None:
        return Fault(
            "container-unknown",
            f"{kind} '{own}' holds '{held}', which names no statement of this page",
        )
    if component == "include":
        return Fault(
            "container-include",
            f"{kind} '{own}' cannot hold include '{held}'",
        )
    if kind == "tabs" and component in INPUT_COMPONENTS:
        return Fault(
            "container-input",
            f"tabs '{own}' cannot hold input '{held}'; "
            "tabs hide panels but inputs must stay visible (use columns)",
        )
    return None


def _nest_fault(kind: str, own: str, held: str, holds: dict[str, list[str]]) -> Fault:
    rule = "container-cycle" if _chain_back(held, own, holds) else "container-nested"
    message = f"{kind} '{own}' cannot hold container '{held}'; containers do not nest"
    return Fault(rule, message)


def container_errors(statements: Statements) -> list[tuple[int, str, str]]:
    """`(line, rule, message)` for the ids containers hold across the whole page."""
    components = {ident: component for _, component, ident, _ in statements}
    holds = {i: held_ids(c, p) for _, c, i, p in statements if c in CONTAINERS}
    taken: dict[str, str] = {}
    errors: list[tuple[int, str, str]] = []
    for line, kind, own, _ in statements:
        for held in holds.get(own, []):
            found = components.get(held)
            fault = _held_fault(kind, own, held, found)
            if found in CONTAINERS:
                fault = _nest_fault(kind, own, held, holds)
            elif held in taken:
                fault = Fault(
                    "container-double", f"'{held}' is already held by '{taken[held]}'"
                )
            taken.setdefault(held, own)
            if fault:
                errors.append((line, fault.rule, fault.message))
    return errors


TABS = BlockSpec(
    "tabs",
    "Tabs that show other blocks of the page, one panel at a time",
    (
        "tab  list of {label, blocks}, 1 to 12; label is the tab text, blocks the ids",
        "     of other statements to show in that panel (up to 200 ids in all)",
        "  A held block is shown once, in its panel, with its own menu. A block is",
        "  held by one container only, and containers do not nest. Input blocks",
        "  (choice, form, comment, ranking, slider, decision) cannot be held in tabs.",
        "  Without script and in print every panel shows, stacked under its label.",
    ),
    r"""tabs = tabs(
  tab: [
    {"label": "Code", "blocks": ["code"]},
    {"label": "Checks", "blocks": ["checklist"]},
  ],
)
""",
    validate_tabs,
)

COLUMNS = BlockSpec(
    "columns",
    "Side-by-side columns that show other blocks of the page",
    (
        "col  list of {label, blocks}, 1 to 4; label is optional text above a column,",
        "     blocks the ids of other statements to show there",
        "  Columns stack below 44rem. A held block is shown once, with its own menu;",
        "  a block is held by one container only and containers do not nest.",
    ),
    r"""columns = columns(
  col: [
    {"label": "Before", "blocks": ["callout"]},
    {"label": "After", "blocks": ["code"]},
  ],
)
""",
    validate_columns,
)
