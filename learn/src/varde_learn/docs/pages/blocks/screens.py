"""Block types for screens: wireframe, ui-states."""

from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    list_of,
    str_field,
    str_map,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec

_REQUIRED_STATES = ("empty", "loading", "error")
_BLANK = " ."
SURFACES = ("browser", "phone", "tablet")
KINDS = ("nav", "text", "media", "input", "action", "list")
LAYOUTS = ("tabs", "grid")
_FRAME_OPTIONAL = {"kinds", "notes"}


def _grid_faults(data: dict[str, object], where: str) -> list[Fault]:
    faults = list_of(data.get("grid"), f"{where}.grid") if "grid" in data else []
    if "regions" in data:
        faults += str_map(data["regions"], f"{where}.regions")
    grid = data.get("grid")
    rows = [r for r in grid if isinstance(r, str)] if isinstance(grid, list) else []
    if len({len(r) for r in rows}) > 1:
        faults.append(Fault("grid-width", f"{where}.grid rows must have equal width"))
    regions = data.get("regions")
    if not isinstance(regions, dict):
        return faults
    faults += [
        Fault("type", f"{where}.regions key '{k}' must be one character")
        for k in sorted(regions)
        if len(k) != 1 or k in _BLANK
    ]
    used = {c for r in rows for c in r if c not in _BLANK}
    faults += [
        Fault("region-undeclared", f"{where}.grid uses '{c}' with no entry in regions")
        for c in sorted(used - regions.keys())
    ]
    faults += [
        Fault("region-unused", f"{where}.regions '{k}' does not appear in the grid")
        for k in sorted(regions.keys() - used)
        if len(k) == 1
    ]
    return faults


def _kind_faults(data: dict[str, object], where: str) -> list[Fault]:
    kinds = data.get("kinds")
    if "kinds" not in data:
        return []
    if not isinstance(kinds, dict) or not kinds:
        return [Fault("type", f"{where}.kinds must be a non-empty table of kinds")]
    regions = data.get("regions")
    declared = regions if isinstance(regions, dict) else {}
    faults = [
        Fault("kind-unknown", f"{where}.kinds '{k}' is not one of {', '.join(KINDS)}")
        for k, v in sorted(kinds.items())
        if v not in KINDS
    ]
    return faults + [
        Fault("kind-region", f"{where}.kinds '{k}' is not a declared region")
        for k in sorted(kinds)
        if k not in declared
    ]


def _note_faults(data: dict[str, object], where: str) -> list[Fault]:
    notes = data.get("notes")
    if "notes" not in data:
        return []
    if not isinstance(notes, list) or not notes:
        return [Fault("type", f"{where}.notes must be a non-empty list of tables")]
    regions = data.get("regions")
    declared = regions if isinstance(regions, dict) else {}
    faults: list[Fault] = []
    for n, note in enumerate(notes, 1):
        at = f"{where}.notes[{n}]"
        if not isinstance(note, dict):
            faults.append(Fault("type", f"{at} must be a table with region and text"))
            continue
        faults += check_keys(note, {"region", "text"}, set(), at)
        faults += str_field(note, "text", at)
        region = note.get("region")
        if "region" in note and region not in declared:
            faults.append(
                Fault("note-region", f"{at}: region '{region}' is not declared")
            )
    return faults


def _frame_faults(data: dict[str, object], where: str) -> list[Fault]:
    return (
        _grid_faults(data, where)
        + _kind_faults(data, where)
        + _note_faults(data, where)
    )


def validate_wireframe(data: dict[str, object]) -> list[Fault]:
    optional = {"title", "surface", "compare"} | _FRAME_OPTIONAL
    faults = check_keys(data, {"grid", "regions"}, optional, "wireframe")
    faults += str_field(data, "title", "wireframe")
    if "surface" in data and data["surface"] not in SURFACES:
        faults.append(
            Fault("surface", f"wireframe.surface must be one of {', '.join(SURFACES)}")
        )
    faults += _frame_faults(data, "wireframe")
    after = data.get("compare")
    if "compare" not in data:
        return faults
    if not isinstance(after, dict):
        return faults + [Fault("type", "wireframe.compare must be a table")]
    faults += check_keys(
        after, {"grid", "regions"}, _FRAME_OPTIONAL, "wireframe.compare"
    )
    return faults + _frame_faults(after, "wireframe.compare")


def _state_faults(name: str, state: object) -> list[Fault]:
    where = f"ui-states.{name}"
    if not isinstance(state, dict):
        return [Fault("type", f"{where} must be a table with shows or na")]
    faults = check_keys(state, set(), {"shows", "na"}, where)
    if ("shows" in state) == ("na" in state):
        faults.append(Fault("state-form", f"{where}: give exactly one of shows or na"))
    return faults + str_field(state, "shows", where) + str_field(state, "na", where)


def validate_ui_states(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, set(), {"screen", "layout"}, "ui-states")
    faults = [f for f in faults if f.rule != "unknown-key" or "'" not in f.message]
    faults += str_field(data, "screen", "ui-states")
    if isinstance(data.get("layout"), str) and data["layout"] not in LAYOUTS:
        faults.append(
            Fault("layout", f"ui-states.layout must be one of {', '.join(LAYOUTS)}")
        )
    faults += [
        Fault(
            "ui-state-missing",
            f"ui-states: state '{name}' is missing; "
            "describe it or mark it na with a reason",
        )
        for name in _REQUIRED_STATES
        if name not in data
    ]
    for name, state in data.items():
        if name != "screen" and not (name == "layout" and isinstance(state, str)):
            faults += _state_faults(name, state)
    return faults


WIREFRAME = BlockSpec(
    "wireframe",
    "Screen regions laid out on a text grid",
    (
        "title    optional text",
        "grid     equal-width strings; a letter is a region, space or . is empty",
        "regions  one-letter key = region label; every letter in grid must be declared",
        "surface  optional device frame: browser, phone or tablet",
        "kinds    optional one-letter key = nav, text, media, input, action or list;",
        "         each kind has its own hatch pattern and a [kind] label",
        "notes    optional list of {region, text}; numbered pins and a notes list",
        "compare  optional second frame {grid, regions, kinds, notes}; the main frame",
        "         is Before and compare is After (side by side on wide screens)",
    ),
    r"""wireframe = wireframe(
  title: "Orders list",
  surface: "browser",
  grid: ["HHHHHH", "SSLLLL", "SSLLLL", "FFFFFF"],
  regions: {"H": "header", "S": "filters", "L": "order list", "F": "footer"},
  kinds: {"H": "nav", "S": "input", "L": "list"},
  notes: [{"region": "S", "text": "Filters stay in the URL"}],
)
""",
    validate_wireframe,
)

UI_STATES = BlockSpec(
    "ui-states",
    "What a screen shows when empty, loading and failing",
    (
        "screen          optional screen name",
        "layout          optional: tabs (one state at a time, default) or grid",
        "[empty]         required; shows = text, or na = reason it cannot occur",
        "[loading]       required; same form",
        "[error]         required; same form",
        "[<other>]       optional extra state in the same form",
    ),
    r"""ui-states = ui-states(
  screen: "Orders list",
  empty: {"shows": "No orders yet, with a Create order button"},
  loading: {"shows": "Skeleton rows"},
  error: {"shows": "Message and a Retry button"},
)
""",
    validate_ui_states,
)
