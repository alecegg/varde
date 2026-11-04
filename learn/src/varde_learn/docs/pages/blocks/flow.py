"""Block type for process: flow."""

from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    duplicates,
    list_of,
    str_field,
    tables,
    tables_fault,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec


def validate_flow(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"step"}, {"title"}, "flow")
    faults += str_field(data, "title", "flow") + tables_fault(data, "step", "flow")
    steps = tables(data, "step", "flow")
    ids = [n for s in steps if isinstance(n := s.get("id"), str)]
    faults += [
        Fault("step-duplicate", f"flow: step id '{name}' is used more than once")
        for name in duplicates(ids)
    ]
    for n, step in enumerate(steps, 1):
        where = f"step[{n}]"
        faults += check_keys(step, {"id", "text"}, {"next"}, where)
        faults += str_field(step, "id", where) + str_field(step, "text", where)
        if "next" not in step:
            continue
        faults += list_of(step["next"], f"{where}.next")
        targets = step["next"] if isinstance(step["next"], list) else []
        faults += [
            Fault("step-target", f"{where}: next '{t}' is not a step id")
            for t in targets
            if isinstance(t, str) and t not in ids
        ]
    return faults


FLOW = BlockSpec(
    "flow",
    "Steps and the steps that can follow each",
    (
        "title        optional text",
        "step: list of {id, text, next}, one per step",
        "  id    unique step name",
        "  text  what happens",
        "  next  optional list of step ids; several entries are branches",
    ),
    r"""flow = flow(
  title: "Checkout",
  step: [
    {"id": "cart", "text": "Review cart", "next": ["pay"]},
    {"id": "pay", "text": "Pay", "next": ["done", "failed"]},
    {"id": "done", "text": "Show receipt"},
    {"id": "failed", "text": "Show error", "next": ["pay"]},
  ],
)
""",
    validate_flow,
)
