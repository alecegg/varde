"""Validate typed blocks in a document. Pure: text in, errors out."""

import re
from dataclasses import dataclass
from pathlib import Path

from varde_learn.docs.pages.blocks.annotated_code import ANNOTATED_CODE
from varde_learn.docs.pages.blocks.backend import DATA_MODEL, ENDPOINT
from varde_learn.docs.pages.blocks.callout import CALLOUT
from varde_learn.docs.pages.blocks.change_summary import CHANGE_SUMMARY
from varde_learn.docs.pages.blocks.charts import CHART
from varde_learn.docs.pages.blocks.checklist import CHECKLIST
from varde_learn.docs.pages.blocks.code import CODE
from varde_learn.docs.pages.blocks.containers import COLUMNS, TABS, container_errors
from varde_learn.docs.pages.blocks.decision import DECISION
from varde_learn.docs.pages.blocks.deps import DEPS
from varde_learn.docs.pages.blocks.diagrams import DIAGRAM
from varde_learn.docs.pages.blocks.diff import DIFF
from varde_learn.docs.pages.blocks.fences import find_fences
from varde_learn.docs.pages.blocks.file_tree import FILE_TREE
from varde_learn.docs.pages.blocks.flow import FLOW
from varde_learn.docs.pages.blocks.image import IMAGE
from varde_learn.docs.pages.blocks.include import INCLUDE
from varde_learn.docs.pages.blocks.inputs import CHOICE, COMMENT, FORM
from varde_learn.docs.pages.blocks.inputs_ordered import RANKING, SLIDER
from varde_learn.docs.pages.blocks.option_matrix import MATRIX
from varde_learn.docs.pages.blocks.recap import RECAP
from varde_learn.docs.pages.blocks.risk import RISK
from varde_learn.docs.pages.blocks.rules import Fault
from varde_learn.docs.pages.blocks.screen_flow import SCREEN_FLOW
from varde_learn.docs.pages.blocks.screens import UI_STATES, WIREFRAME
from varde_learn.docs.pages.blocks.sequence import SEQUENCE
from varde_learn.docs.pages.blocks.spec import BlockSpec
from varde_learn.docs.pages.blocks.state import STATE
from varde_learn.docs.pages.blocks.stats import STATS
from varde_learn.docs.pages.blocks.tables import TABLE
from varde_learn.docs.pages.blocks.timeline import TIMELINE

SPECS: dict[str, BlockSpec] = {
    s.name: s
    for s in (DATA_MODEL, ENDPOINT, WIREFRAME, UI_STATES, FLOW, TABLE, CHART, DECISION)
}
# Every component a `ui` statement may name.
COMPONENT_SPECS: dict[str, BlockSpec] = {
    **SPECS,
    "recap": RECAP,
    "deps": DEPS,
    "diagram": DIAGRAM,
    "include": INCLUDE,
    "choice": CHOICE,
    "form": FORM,
    "comment": COMMENT,
    "ranking": RANKING,
    "slider": SLIDER,
    "callout": CALLOUT,
    "code": CODE,
    "annotated-code": ANNOTATED_CODE,
    "file-tree": FILE_TREE,
    "diff": DIFF,
    "checklist": CHECKLIST,
    "stats": STATS,
    "timeline": TIMELINE,
    "tabs": TABS,
    "columns": COLUMNS,
    "matrix": MATRIX,
    "sequence": SEQUENCE,
    "risks": RISK,
    "state": STATE,
    "screen-flow": SCREEN_FLOW,
    "image": IMAGE,
    "change-summary": CHANGE_SUMMARY,
}
CUSTOM_REMOVED = (
    "the `custom` block was removed; use `ui` components (`varde learn docs blocks`)"
)
ID_RULE = re.compile(r"^[a-z][a-z0-9-]{0,47}$")


@dataclass(frozen=True)
class BlockError:
    line: int  # 1-based document line
    rule: str
    message: str

    def text(self) -> str:
        return f"line {self.line}: {self.rule}: {self.message}"


def _covers_faults(data: dict[str, object]) -> list[Fault]:
    covers = data.get("covers")
    if covers is None:
        return []
    ok = isinstance(covers, list) and all(
        isinstance(c, str) and ID_RULE.match(c) for c in covers
    )
    if ok:
        return []
    return [Fault("covers", "covers must be a list of block ids")]


# Fence languages that held page data before the line syntax: the TOML typed
# fences and the JSON `recap` and plain-text `deps` fences.
OLD_FENCES = frozenset({*SPECS, "recap", "deps"})
TOML_FENCE_REMOVED = (
    "typed fences were replaced by `ui` statements; "
    "rewrite this one as a statement (`varde learn docs blocks <type>`) "
    "(for ordinary code, use another language tag)"
)


def _old_fence_errors(doc_text: str) -> list[BlockError]:
    return [
        BlockError(
            f.line, "toml-fence-removed", f"`{f.lang}` fence: {TOML_FENCE_REMOVED}"
        )
        for f in find_fences(doc_text, OLD_FENCES)
    ]


def _duplicate_id(
    ident: str, line: int, first_seen: dict[str, int]
) -> list[BlockError]:
    """An id already used by an earlier fence (the parser covers one fence)."""
    if ident in first_seen:
        message = (
            f"id '{ident}' is already used by the statement at line {first_seen[ident]}"
        )
        return [BlockError(line, "id-duplicate", message)]
    first_seen[ident] = line
    return []


def _ui_errors(doc_text: str, root: Path | None) -> list[BlockError]:
    """Parse, props, include and heading-id errors for a document's `ui` text."""
    # Lazy: these import the page renderer and line parser, which import this package.
    from varde_learn.docs.pages.include import include_errors
    from varde_learn.docs.pages.lines import parse_lines
    from varde_learn.docs.pages.select import heading_id_errors

    errors: list[BlockError] = []
    first_seen: dict[str, int] = {}
    held: list[tuple[int, str, str, dict[str, object]]] = []
    for fence in find_fences(doc_text, frozenset({"ui"})):
        result = parse_lines(fence.body)
        errors += [
            BlockError(fence.line + e.line, e.rule, e.message) for e in result.errors
        ]
        for statement in result.statements:
            line = fence.line + statement.line
            errors += _duplicate_id(statement.id, line, first_seen)
            errors += check_props(statement.component, statement.props, line)
            held.append((line, statement.component, statement.id, statement.props))
    errors += [BlockError(*found) for found in container_errors(held)]
    found = include_errors(doc_text, root) + heading_id_errors(doc_text)
    errors += [BlockError(line, rule, message) for line, rule, message in found]
    return list(dict.fromkeys(errors))  # include faults arrive from both validators


def _custom_errors(doc_text: str) -> list[BlockError]:
    fences = find_fences(doc_text, frozenset({"custom"}))
    return [BlockError(f.line, "custom-block-removed", CUSTOM_REMOVED) for f in fences]


def check(doc_text: str, root: Path | None = None) -> list[BlockError]:
    """Return every block error in document order.

    `root` is the page's directory; with it each `include` source must resolve.
    """
    errors = _old_fence_errors(doc_text)
    errors += _ui_errors(doc_text, root)
    errors += _custom_errors(doc_text)
    return sorted(errors, key=lambda error: error.line)


def check_props(
    component: str, props: dict[str, object], line: int
) -> list[BlockError]:
    """Errors for one parsed statement's props (parsed from a `ui` statement)."""
    spec = COMPONENT_SPECS.get(component)
    if spec is None:
        known = ", ".join(sorted(COMPONENT_SPECS))
        message = f"unknown component '{component}'; known: {known}"
        return [BlockError(line, "component-unknown", message)]
    data = dict(props)
    faults = _covers_faults(data)
    data.pop("covers", None)
    faults += spec.validate(data)
    return [BlockError(line, f.rule, f.message) for f in faults]
