"""Block type for a multi-screen wireframe flow: screens, steps and optional lanes."""

from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    duplicates,
    list_of,
    str_field,
    tables,
    tables_fault,
)
from varde_learn.docs.pages.blocks.screens import SURFACES, _frame_faults
from varde_learn.docs.pages.blocks.spec import BlockSpec

MAX_SCREENS = 12
MAX_STEPS = 20
SCREEN_KEYS = {"id", "title", "grid", "regions"}
SCREEN_OPTIONAL = {"surface", "kinds", "notes"}
WHERE = "screen-flow"


def _screen_faults(data: dict[str, object]) -> tuple[list[Fault], list[str]]:
    faults = tables_fault(data, "screens", WHERE)
    entries = tables(data, "screens", WHERE)
    ids = [i for s in entries if isinstance(i := s.get("id"), str)]
    faults += [
        Fault("screen-duplicate", f"{WHERE}: screen id '{name}' is used twice")
        for name in duplicates(ids)
    ]
    if len(entries) > MAX_SCREENS:
        faults.append(Fault("too-many", f"{WHERE}: at most {MAX_SCREENS} screens"))
    for n, screen in enumerate(entries, 1):
        where = f"screens[{n}]"
        faults += check_keys(screen, SCREEN_KEYS, SCREEN_OPTIONAL, where)
        faults += str_field(screen, "id", where) + str_field(screen, "title", where)
        if "surface" in screen and screen["surface"] not in SURFACES:
            faults.append(
                Fault(
                    "surface", f"{where}.surface must be one of {', '.join(SURFACES)}"
                )
            )
        faults += _frame_faults(screen, where)
    return faults, ids


def _end_fault(step: dict[str, object], key: str, ids: list[str], where: str):
    end = step.get(key)
    if key not in step:
        return []
    if not isinstance(end, str):
        return [Fault("type", f"{where}.{key} must be a string")]
    if end not in ids:
        return [Fault("step-screen", f"{where}: {key} '{end}' is not a screen id")]
    return []


def _step_faults(data: dict[str, object], ids: list[str]) -> list[Fault]:
    faults = tables_fault(data, "steps", WHERE)
    steps = tables(data, "steps", WHERE)
    if len(steps) > MAX_STEPS:
        faults.append(Fault("too-many", f"{WHERE}: at most {MAX_STEPS} steps"))
    for n, step in enumerate(steps, 1):
        where = f"steps[{n}]"
        faults += check_keys(step, {"from", "to"}, {"label"}, where)
        faults += _end_fault(step, "from", ids, where)
        faults += _end_fault(step, "to", ids, where)
        faults += str_field(step, "label", where)
    return faults


def _lane_faults(data: dict[str, object], ids: list[str]) -> list[Fault]:
    faults = tables_fault(data, "lanes", WHERE)
    lanes = tables(data, "lanes", WHERE)
    placed: list[str] = []
    for n, lane in enumerate(lanes, 1):
        where = f"lanes[{n}]"
        faults += check_keys(lane, {"title", "screens"}, set(), where)
        faults += str_field(lane, "title", where)
        if "screens" in lane:
            faults += list_of(lane["screens"], f"{where}.screens")
        members = lane.get("screens")
        names = (
            [m for m in members if isinstance(m, str)]
            if isinstance(members, list)
            else []
        )
        faults += [
            Fault("lane-screen", f"{where}: '{name}' is not a screen id")
            for name in names
            if name not in ids
        ]
        placed += names
    if not lanes:
        return faults
    faults += [
        Fault("lane-duplicate", f"{WHERE}: screen '{name}' is in more than one lane")
        for name in duplicates(placed)
    ]
    return faults + [
        Fault("lane-missing", f"{WHERE}: screen '{name}' is in no lane")
        for name in ids
        if name not in placed
    ]


def _lane_of(data: dict[str, object]) -> dict[str, int]:
    """Lane index per screen id; empty when no lanes are declared."""
    out: dict[str, int] = {}
    for k, lane in enumerate(tables(data, "lanes", WHERE)):
        members = lane.get("screens")
        for name in members if isinstance(members, list) else []:
            if isinstance(name, str):
                out[name] = k
    return out


def _pairs(data: dict[str, object], ids: list[str]) -> list[tuple[str, str]]:
    steps = tables(data, "steps", WHERE)
    return [
        (a, b)
        for s in steps
        if isinstance(a := s.get("from"), str) and isinstance(b := s.get("to"), str)
        if a in ids and b in ids
    ]


def _flow_faults(data: dict[str, object], ids: list[str]) -> list[Fault]:
    """Cycles, then lanes and ranks: a step joins neighbouring ranks of one lane."""
    # Imported here: the renderer package imports this one at load time.
    from varde_learn.docs.pages.blocks_render.diagram_layout import (
        assign_layers,
        back_edges,
    )

    pairs = _pairs(data, ids)
    faults = [
        Fault("step-duplicate", f"{WHERE}: step '{a}' to '{b}' is given twice")
        for a, b in sorted({p for p in pairs if pairs.count(p) > 1})
    ]
    pairs = list(dict.fromkeys(pairs))
    loops = sorted(back_edges(ids, pairs))
    if loops:
        return faults + [
            Fault(
                "cycle",
                f"{WHERE}: step '{pairs[i][0]}' to '{pairs[i][1]}' closes a cycle; "
                "a flow runs one way",
            )
            for i in loops
        ]
    rank, lane = assign_layers(ids, pairs), _lane_of(data)
    for a, b in pairs:
        if lane.get(a, 0) != lane.get(b, 0):
            faults.append(
                Fault(
                    "step-lane",
                    f"{WHERE}: step '{a}' to '{b}' crosses lanes; "
                    "put both screens in one lane",
                )
            )
        elif rank[b] != rank[a] + 1:
            faults.append(
                Fault(
                    "step-rank",
                    f"{WHERE}: step '{a}' to '{b}' skips a rank; "
                    "add an intermediate screen between them",
                )
            )
    cells: dict[tuple[int, int], list[str]] = {}
    for name in ids:
        cells.setdefault((rank[name], lane.get(name, 0)), []).append(name)
    return faults + [
        Fault(
            "cell-taken",
            f"{WHERE}: screens {', '.join(repr(m) for m in members)} share a lane "
            "and a rank; give one its own lane or chain them with a step",
        )
        for members in cells.values()
        if len(members) > 1
    ]


def validate_screen_flow(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"screens"}, {"title", "desc", "steps", "lanes"}, WHERE)
    faults += str_field(data, "title", WHERE) + str_field(data, "desc", WHERE)
    screen_faults, ids = _screen_faults(data)
    faults += screen_faults + _step_faults(data, ids) + _lane_faults(data, ids)
    if faults:
        return faults
    return _flow_faults(data, ids)


SCREEN_FLOW = BlockSpec(
    "screen-flow",
    "A flow of wireframe screens in lanes, joined by labelled arrows",
    (
        "screens: list of {id, title, grid, regions, surface, kinds, notes}, 1 to 12",
        "  id, title  unique screen name and its caption",
        "  grid, regions, surface, kinds, notes  as in wireframe (drawn at half size)",
        "steps: optional list of {from, to, label}, up to 20",
        "  from, to  screen ids; a step joins neighbouring ranks of one lane",
        "  label     optional text on the arrow",
        "  A step across lanes or over a rank is a fault: add an intermediate screen.",
        "  A cycle is a fault; one screen per lane and rank.",
        "lanes: optional list of {title, screens: [id]}; every screen in one lane",
        "title, desc  optional text; desc is a one-sentence summary",
        "  Screens read left to right (top to bottom on phones); select one to hear",
        "  its notes. The screens are always also listed as text, in step order.",
    ),
    r"""screen-flow = screen-flow(
  title: "Checkout",
  desc: "The buyer picks a cart, pays, and sees a receipt.",
  screens: [
    {"id": "cart", "title": "Cart", "surface": "phone",
     "grid": ["HH", "LL", "BB"], "regions": {"H": "header", "L": "lines", "B": "pay"},
     "kinds": {"L": "list", "B": "action"},
     "notes": [{"region": "B", "text": "Disabled while the cart is empty"}]},
    {"id": "pay", "title": "Payment", "surface": "phone",
     "grid": ["HH", "FF", "BB"], "regions": {"H": "header", "F": "card", "B": "pay"},
     "kinds": {"F": "input", "B": "action"}},
    {"id": "done", "title": "Receipt", "surface": "phone",
     "grid": ["HH", "RR"], "regions": {"H": "header", "R": "receipt"}},
  ],
  steps: [
    {"from": "cart", "to": "pay", "label": "Pay"},
    {"from": "pay", "to": "done", "label": "Card accepted"},
  ],
)
""",
    validate_screen_flow,
)
