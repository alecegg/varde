"""Component `include`: a selected part of another markdown file.

Props are `source`, `select` and an optional `title`. The page assembler renders
an include through `pages.include` (confined file reads), not a props renderer.
This module holds only the pure statement checks and the selector grammar
(`heading:<anchor>`, `task:<id>`, `frontmatter`, `acceptance`, `lines:<a>-<b>`).
"""

import re
from dataclasses import dataclass

from varde_learn.docs.pages.blocks.rules import Fault, check_keys
from varde_learn.docs.pages.blocks.spec import BlockSpec

ANCHOR = re.compile(r"^[a-z0-9-]+(/[0-9]+)?$")
TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_LINES = re.compile(r"^lines:([0-9]+)-([0-9]+)$")


class SelectorError(ValueError):
    """The selector is malformed or selects nothing in this source."""


@dataclass(frozen=True)
class Selector:
    kind: str  # heading, task, frontmatter, acceptance, lines
    arg: str = ""
    first: int = 0  # `lines:` only, 1-based
    last: int = 0


def parse_selector(text: str) -> Selector:
    if text in {"frontmatter", "acceptance"}:
        return Selector(text)
    kind, _, arg = text.partition(":")
    if kind == "heading" and ANCHOR.match(arg):
        return Selector("heading", arg)
    if kind == "task" and TASK_ID.match(arg):
        return Selector("task", arg)
    match = _LINES.match(text)
    if match and 1 <= int(match.group(1)) <= int(match.group(2)):
        return Selector("lines", first=int(match.group(1)), last=int(match.group(2)))
    raise SelectorError(
        f"selector '{text}' must be heading:<anchor>, task:<id>, frontmatter, "
        "acceptance or lines:<a>-<b>"
    )


def include_faults(props: dict[str, object]) -> list[Fault]:
    """Faults in one `include` statement's props."""
    faults = check_keys(dict(props), {"source", "select"}, {"title"}, "include")
    for key in ("source", "select", "title"):
        value = props.get(key)
        if key in props and not (isinstance(value, str) and value.strip()):
            faults.append(Fault("type", f"include.{key} must be a non-empty string"))
    selector = props.get("select")
    if isinstance(selector, str) and selector.strip():
        try:
            parse_selector(selector)
        except SelectorError as error:
            faults.append(Fault("selector", str(error)))
    return faults


INCLUDE = BlockSpec(
    "include",
    "A selected part of another markdown file (plan, task, review), rendered in place",
    (
        "source  path to a .md file under the page's directory or the plan store",
        "select  heading:<anchor>, task:<id>, frontmatter, acceptance or lines:<a>-<b>",
        "title   optional caption",
    ),
    r"""include = include(
  source: "plan.md",
  select: "acceptance",
)
""",
    include_faults,
)
