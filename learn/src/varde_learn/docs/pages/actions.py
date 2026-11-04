"""Per-block action menu: block types, allowed row kinds, menu entries.

Pure data and functions (no I/O, no `render.py`). The page renderer tags each
block with a type; the client menu shows `menu_entries`; `store_comment`
refuses a row kind `kind_allowed` says the type cannot take.

Types: `prose`, `heading`, `list`, `table` (markdown), `code` (fenced code and
the `code` and `diff` components), `widget` (input components), `decision`,
`visual` (any other component that carries a `data-copy` text: chart, diagram, flow,
wireframe, ui-states, endpoint, data-model, table, callout, annotated-code,
file-tree, checklist, stats, timeline, tabs, columns, matrix, sequence, state,
screen-flow, risks, change-summary), `status`
(recap, deps: no copy text),
`part` (a block of an
included part) and `error`.
"""

from collections.abc import Mapping

from varde_learn.docs.pages.blocks_render.registry import COMPONENTS

BLOCK_TYPES: tuple[str, ...] = (
    "prose",
    "heading",
    "list",
    "table",
    "code",
    "widget",
    "decision",
    "visual",
    "status",
    "part",
    "error",
)

_TEXT = frozenset({"comment", "suggestion"})
_COMMENT = frozenset({"comment"})
_INPUT = frozenset({"comment", "answer"})

ALLOWED_KINDS: Mapping[str, frozenset[str]] = {
    "prose": _TEXT,
    "heading": _TEXT,
    "list": _TEXT,
    "table": _TEXT,
    "code": _COMMENT,
    "widget": _INPUT,
    "decision": _INPUT,
    "visual": _COMMENT,
    "status": frozenset({"comment", "drift"}),
    "part": _COMMENT,
    "error": _COMMENT,
}

# Types whose block has nothing to copy (no `data-copy`, no text of its own).
_NO_COPY = frozenset({"widget", "decision", "status"})
# Types the source owns, so a direct edit of this document is not offered.
_NO_EDIT = frozenset({"part"})
_DECISION = "decision"


def kind_allowed(block_type: str, kind: str) -> bool:
    return kind in ALLOWED_KINDS.get(block_type, frozenset())


def menu_entries(
    block_type: str, *, allow_edit: bool, in_part: bool
) -> tuple[str, ...]:
    """Entry ids in menu order; a row-writing entry needs its kind accepted."""
    entries = ["comment"]
    if kind_allowed(block_type, "suggestion") and not in_part:
        entries.append("suggest")
    if allow_edit and not in_part and block_type not in _NO_EDIT:
        entries.append("edit")
    if block_type not in _NO_COPY:
        entries.append("copy")
    entries.append("copy-link")
    return tuple(entries)


def component_block_type(component: str) -> str:
    """The block type of a `ui` component name (`include` renders as parts)."""
    if component == "include":
        return "part"
    if component in ("code", "diff"):
        return "code"
    entry = COMPONENTS.get(component)
    if entry is None:
        return "error"
    if component == "decision":
        return _DECISION
    if entry.answer_schema is not None:
        return "widget"
    if component in ("recap", "deps"):
        return "status"
    return "visual"
