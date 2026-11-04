"""Block type for asking the user to approve, deny or comment."""

from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    duplicates,
    str_field,
    tables,
    tables_fault,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec

OPTIONS = ("approve", "deny", "comment")


def _option_faults(data: dict[str, object]) -> list[Fault]:
    if "options" not in data:
        return []
    options = data["options"]
    if not isinstance(options, list) or not options:
        return [Fault("type", "decision.options must be a non-empty list")]
    faults = [
        Fault("option-unknown", f"decision.options: unknown option '{o}'")
        for o in options
        if o not in OPTIONS
    ]
    names = [o for o in options if isinstance(o, str)]
    faults += [
        Fault("option-duplicate", f"decision.options: '{o}' is listed twice")
        for o in duplicates(names)
    ]
    return faults


def _evidence_faults(data: dict[str, object]) -> list[Fault]:
    faults = tables_fault(data, "evidence", "decision")
    for index, row in enumerate(tables(data, "evidence", "decision"), start=1):
        where = f"decision.evidence[{index}]"
        faults += check_keys(row, {"label", "text"}, set(), where)
        faults += str_field(row, "label", where) + str_field(row, "text", where)
    return faults


def validate_decision(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"question"}, {"options", "evidence", "diff"}, "decision")
    faults += str_field(data, "question", "decision")
    faults += str_field(data, "diff", "decision")
    return faults + _option_faults(data) + _evidence_faults(data)


DECISION = BlockSpec(
    "decision",
    "A question the user answers with approve, deny or a comment",
    (
        "question  required text",
        "options   optional list of approve, deny, comment; default all three",
        "evidence  optional list of {label, text} rows",
        "  label  optional short label",
        "  text   the row's text",
        "diff      optional text, shown preformatted",
    ),
    r"""decision = decision(
  question: "Accept the shorter build-skill intro?",
  options: ["approve", "deny", "comment"],
  diff: "- Read the whole file first.\n+ Read the task file first.",
  evidence: [
    {"label": "friction", "text": "3 sessions skipped the intro"},
    {"label": "token delta", "text": "-120 tokens per run"},
  ],
)
""",
    validate_decision,
)
