"""Block type for settled notes: callout."""

from varde_learn.docs.pages.blocks.rules import Fault, check_keys, str_field
from varde_learn.docs.pages.blocks.spec import BlockSpec

TONES = ("info", "decision", "risk", "warning", "success")


def validate_callout(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"tone", "text"}, {"title"}, "callout")
    faults += str_field(data, "text", "callout") + str_field(data, "title", "callout")
    tone = data.get("tone")
    if "tone" in data and tone not in TONES:
        faults.append(Fault("tone", f"callout: tone must be one of {', '.join(TONES)}"))
    return faults


CALLOUT = BlockSpec(
    "callout",
    "A tinted note with a tone, a label and plain text",
    (
        "tone   info, decision, risk, warning or success; the label shows its word",
        "title  optional short heading",
        "text   plain text; a blank line starts a paragraph, `code` marks inline code",
    ),
    r"""callout = callout(
  tone: "decision",
  title: "Storage",
  text: "Use SQLite for the `queue` table; one writer is enough.",
)
""",
    validate_callout,
)
