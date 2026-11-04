"""Block type for a sequence diagram: actors, ordered steps, optional groups."""

from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    duplicates,
    str_field,
    tables,
    tables_fault,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec

KINDS = ("call", "return", "async", "note")
MAX_ACTORS = 12
MAX_STEPS = 200
ACTOR_OPTIONAL: set[str] = set()
STEP_OPTIONAL = {"kind", "group"}


def _actor_faults(data: dict[str, object]) -> tuple[list[Fault], list[str]]:
    faults = tables_fault(data, "actors", "sequence")
    entries = tables(data, "actors", "sequence")
    names = [n for a in entries if isinstance(n := a.get("id"), str)]
    faults += [
        Fault("actor-duplicate", f"sequence: actor id '{name}' is used more than once")
        for name in duplicates(names)
    ]
    if len(entries) > MAX_ACTORS:
        faults.append(Fault("too-many", f"sequence: at most {MAX_ACTORS} actors"))
    for n, actor in enumerate(entries, 1):
        where = f"actors[{n}]"
        faults += check_keys(actor, {"id", "label"}, ACTOR_OPTIONAL, where)
        faults += str_field(actor, "id", where) + str_field(actor, "label", where)
    return faults, names


def _end_fault(step: dict[str, object], key: str, actors: list[str], where: str):
    end = step.get(key)
    if key not in step:
        return []
    if not isinstance(end, str):
        return [Fault("type", f"{where}.{key} must be a string")]
    if end not in actors:
        return [Fault("step-actor", f"{where}: {key} '{end}' is not an actor id")]
    return []


def _step_faults(step: dict[str, object], actors: list[str], where: str) -> list[Fault]:
    faults = check_keys(step, {"from", "to", "text"}, STEP_OPTIONAL, where)
    faults += _end_fault(step, "from", actors, where)
    faults += _end_fault(step, "to", actors, where)
    faults += str_field(step, "text", where) + str_field(step, "group", where)
    if "kind" in step and step["kind"] not in KINDS:
        faults.append(Fault("type", f"{where}: kind must be one of {list(KINDS)}"))
    return faults


def _steps_faults(data: dict[str, object], actors: list[str]) -> list[Fault]:
    faults = tables_fault(data, "steps", "sequence")
    entries = tables(data, "steps", "sequence")
    if len(entries) > MAX_STEPS:
        faults.append(Fault("too-many", f"sequence: at most {MAX_STEPS} steps"))
    for n, step in enumerate(entries, 1):
        faults += _step_faults(step, actors, f"steps[{n}]")
    return faults


def validate_sequence(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"actors", "steps", "desc"}, {"title"}, "sequence")
    faults += str_field(data, "title", "sequence") + str_field(data, "desc", "sequence")
    actor_faults, actors = _actor_faults(data)
    return faults + actor_faults + _steps_faults(data, actors)


SEQUENCE = BlockSpec(
    "sequence",
    "A sequence diagram of actors and ordered steps, drawn as SVG",
    (
        "actors: list of {id, label}, 1 to 12",
        "  id     unique actor name; label is the text over its lifeline",
        "steps: list of {from, to, text, kind, group}, 1 to 200, in order",
        "  from, to  actor ids; the same id draws a self-call loop",
        "  text      the message",
        "  kind      optional: call (default, solid), return (dashed),",
        "            async (open head) or note (a box across from..to)",
        "  group     optional label; neighbouring steps with the same label sit",
        "            in one labelled frame (alt, loop, opt style)",
        "desc        what the diagram shows, for screen readers",
        "title       optional text",
        "  The steps are always also listed as text: 'A to B: text'.",
    ),
    r"""sequence = sequence(
  title: "Sign in",
  desc: "The browser signs a user in through the API and the user store.",
  actors: [
    {"id": "b", "label": "Browser"},
    {"id": "api", "label": "API"},
    {"id": "db", "label": "Users"},
  ],
  steps: [
    {"from": "b", "to": "api", "text": "POST /login"},
    {"from": "api", "to": "db", "text": "find user", "group": "cache miss"},
    {"from": "db", "to": "api", "text": "row", "kind": "return", "group": "cache miss"},
    {"from": "api", "to": "api", "text": "check password"},
    {"from": "api", "to": "b", "text": "session cookie", "kind": "return"},
  ],
)
""",
    validate_sequence,
)
