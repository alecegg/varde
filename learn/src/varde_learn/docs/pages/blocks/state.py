"""Block type for a state machine: states and labelled transitions."""

from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    duplicates,
    str_field,
    tables,
    tables_fault,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec

KINDS = ("initial", "normal", "final", "error")
MAX_STATES = 40
STATE_OPTIONAL = {"kind", "note"}
MOVE_OPTIONAL = {"label", "guard"}


def _state_faults(data: dict[str, object]) -> tuple[list[Fault], list[str]]:
    faults = tables_fault(data, "states", "state")
    entries = tables(data, "states", "state")
    names = [n for s in entries if isinstance(n := s.get("id"), str)]
    faults += [
        Fault("state-duplicate", f"state: state id '{name}' is used more than once")
        for name in duplicates(names)
    ]
    if len(entries) > MAX_STATES:
        faults.append(Fault("too-many", f"state: at most {MAX_STATES} states"))
    for n, state in enumerate(entries, 1):
        where = f"states[{n}]"
        faults += check_keys(state, {"id", "label"}, STATE_OPTIONAL, where)
        for key in ("id", "label", "note"):
            faults += str_field(state, key, where)
        if "kind" in state and state["kind"] not in KINDS:
            faults.append(Fault("type", f"{where}: kind must be one of {list(KINDS)}"))
    initial = sum(1 for s in entries if s.get("kind") == "initial")
    if entries and initial == 0:
        faults.append(Fault("no-initial", "state: one state must have kind initial"))
    if initial > 1:
        faults.append(Fault("two-initial", "state: only one state may be initial"))
    return faults, names


def _end_fault(move: dict[str, object], key: str, names: list[str], where: str):
    if key not in move:
        return []
    end = move[key]
    if not isinstance(end, str):
        return [Fault("type", f"{where}.{key} must be a string")]
    if end not in names:
        return [Fault("transition-state", f"{where}: {key} '{end}' is not a state id")]
    return []


def _move_faults(data: dict[str, object], names: list[str]) -> list[Fault]:
    faults = tables_fault(data, "transitions", "state")
    for n, move in enumerate(tables(data, "transitions", "state"), 1):
        where = f"transitions[{n}]"
        faults += check_keys(move, {"from", "to"}, MOVE_OPTIONAL, where)
        faults += _end_fault(move, "from", names, where)
        faults += _end_fault(move, "to", names, where)
        faults += str_field(move, "label", where) + str_field(move, "guard", where)
    return faults


def validate_state(data: dict[str, object]) -> list[Fault]:
    required, optional = {"states", "desc"}, {"title", "transitions"}
    faults = check_keys(data, required, optional, "state")
    faults += str_field(data, "title", "state") + str_field(data, "desc", "state")
    state_faults, names = _state_faults(data)
    return faults + state_faults + _move_faults(data, names)


STATE = BlockSpec(
    "state",
    "A state machine: states and labelled transitions, drawn as SVG",
    (
        "states: list of {id, label, kind, note}, 1 to 40",
        "  id     unique state name; label is the text in its box",
        "  kind   optional: initial (exactly one; gets a start dot), normal",
        "         (default), final (double border) or error (cross mark)",
        "  note   optional text shown in the text list",
        "transitions: optional list of {from, to, label, guard}",
        "  from, to  state ids; the same id draws a self-loop",
        "  label     optional event or action; guard is shown as [guard]",
        "desc        what the machine models, for screen readers",
        "title       optional text",
        "  A state no path from the initial state reaches is marked unreachable.",
        "  Transitions are always also listed as text: 'A to B on label [guard]'.",
    ),
    r"""state = state(
  title: "Job",
  desc: "A job waits, runs, and ends done or failed; failed jobs retry.",
  states: [
    {"id": "idle", "label": "Idle", "kind": "initial"},
    {"id": "run", "label": "Running"},
    {"id": "done", "label": "Done", "kind": "final"},
    {"id": "bad", "label": "Failed", "kind": "error"},
  ],
  transitions: [
    {"from": "idle", "to": "run", "label": "start"},
    {"from": "run", "to": "done", "label": "finish"},
    {"from": "run", "to": "bad", "label": "crash"},
    {"from": "bad", "to": "run", "label": "retry", "guard": "attempts < 3"},
    {"from": "run", "to": "run", "label": "heartbeat"},
  ],
)
""",
    validate_state,
)
