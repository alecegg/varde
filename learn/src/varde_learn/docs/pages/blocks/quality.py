"""Page quality warnings (`quality-*`). Pure: document text in, warnings out.

Every rule is a warning; the page check prints them after the errors and never
fails on them. Prose rules read only prose lines (not fences or HTML comments).
"""

import re
from collections.abc import Collection
from dataclasses import dataclass

from varde_learn.docs.pages.blocks.check import BlockError
from varde_learn.docs.pages.blocks.fences import FenceSpan, dedent_lines, scan_fences
from varde_learn.docs.pages.lines import parse_lines
from varde_learn.docs.pages.render import (
    _HEADING,
    slugify,
    split_frontmatter,
    strip_comments,
)

# One phrase per line, lower case.
STALE_PHRASES = (
    "as discussed above",
    "see above",
    "as mentioned earlier",
    "as noted earlier",
)
OPEN_CHOICES = frozenset({"choice", "ranking", "slider", "form", "comment"})
MAX_BARE_RUN = 3  # N: more consecutive non-prose blocks than this on a recap warns

_EXPLICIT_ID = re.compile(r"\s*\{#([a-z0-9-]+)\}\s*$")
_CODE_SPAN = re.compile(r"`[^`]*`")
_TASK_SELECT = "task:"


@dataclass(frozen=True)
class Unit:
    kind: str  # "heading", "prose" or "block"
    line: int  # 1-based document line
    text: str = ""  # heading text or prose line
    component: str = ""  # block: `ui` component, or "" for a non-`ui` fence
    ident: str = ""  # block: statement id
    props: tuple[tuple[str, object], ...] = ()


def split_units(doc_text: str) -> tuple[dict[str, str], list[Unit]]:
    """Frontmatter fields and the page's headings, prose lines and blocks in order."""
    lines = strip_comments(doc_text.expandtabs(4).splitlines())
    fields, body = split_frontmatter(lines)
    lines = [""] * (len(lines) - len(body)) + body
    spans = {span.start: span for span in scan_fences(lines)}
    units: list[Unit] = []
    i = 0
    while i < len(lines):
        span = spans.get(i)
        if span is not None:
            units += _fence_units(lines, span)
            i = len(lines) if span.end is None else span.end + 1
            continue
        units += _line_unit(lines[i], i + 1)
        i += 1
    return fields, units


def _fence_units(lines: list[str], span: FenceSpan) -> list[Unit]:
    line = span.start + 1
    if span.lang != "ui":
        return [Unit("block", line)]
    stop = len(lines) if span.end is None else span.end
    body = "\n".join(dedent_lines(lines[span.start + 1 : stop], span.indent))
    return [
        Unit(
            "block",
            line + s.line,
            component=s.component,
            ident=s.id,
            props=tuple(s.props.items()),
        )
        for s in parse_lines(body).statements
    ]


def _line_unit(text: str, line: int) -> list[Unit]:
    if not text.strip():
        return []
    heading = _HEADING.match(text)
    if heading:
        return [Unit("heading", line, heading.group(2))]
    return [Unit("prose", line, text)]


def first_block_warnings(units: list[Unit]) -> list[BlockError]:
    """The first block after the title and headings must be prose."""
    first = next((u for u in units if u.kind != "heading"), None)
    if first is None or first.kind == "prose":
        return []
    what = f"`{first.component}` block '{first.ident}'" if first.ident else "a fence"
    return [
        BlockError(
            first.line,
            "quality-first-block",
            f"the first block is {what}, not prose; state the outcome first",
        )
    ]


def stale_reference_warnings(units: list[Unit]) -> list[BlockError]:
    """Prose that points at other text by position, so it breaks when excerpted."""
    found: list[BlockError] = []
    for unit in units:
        if unit.kind != "prose":
            continue
        text = _CODE_SPAN.sub("", unit.text).lower()
        for phrase in STALE_PHRASES:
            if phrase in text:
                message = (
                    f"'{phrase}' points at other text; make the sentence stand alone"
                )
                found.append(BlockError(unit.line, "quality-stale-reference", message))
    return found


def open_choice_warnings(units: list[Unit]) -> list[BlockError]:
    """Open choices belong in the last heading section (the closing form)."""
    headings = [u.line for u in units if u.kind == "heading"]
    if not headings:
        return []
    last = headings[-1]
    return [
        BlockError(
            u.line,
            "quality-open-choice",
            f"`{u.component}` block '{u.ident}' is outside the last section; "
            "put open choices in the closing form",
        )
        for u in units
        if u.component in OPEN_CHOICES and u.line < last
    ]


def page_targets(units: list[Unit], task_ids: Collection[str] = ()) -> set[str]:
    """Ids a `covers` entry may name: blocks, heading anchors, task ids."""
    targets: set[str] = set(task_ids)
    for unit in units:
        if unit.ident:
            targets.add(unit.ident)
        if unit.kind == "heading":
            explicit = _EXPLICIT_ID.search(unit.text)
            targets.add(explicit.group(1) if explicit else slugify(unit.text))
        targets |= _task_ids_in(dict(unit.props))
    return targets


def _task_ids_in(props: dict[str, object]) -> set[str]:
    found: set[str] = set()
    select = props.get("select")
    if isinstance(select, str) and select.startswith(_TASK_SELECT):
        found.add(select[len(_TASK_SELECT) :])
    rows = props.get("rows")
    for row in rows if isinstance(rows, list) else []:
        tasks = row.get("tasks") if isinstance(row, dict) else None
        found |= (
            {t for t in tasks if isinstance(t, str)}
            if isinstance(tasks, list)
            else set()
        )
    return found


def covers_warnings(
    units: list[Unit], task_ids: Collection[str] = ()
) -> list[BlockError]:
    """A `covers` id that matches no block, anchor or task id on the page."""
    targets = page_targets(units, task_ids)
    found: list[BlockError] = []
    for unit in units:
        covers = dict(unit.props).get("covers")
        for ref in covers if isinstance(covers, list) else []:
            if isinstance(ref, str) and ref not in targets:
                message = (
                    f"block '{unit.ident}' covers '{ref}', "
                    "which nothing on the page matches"
                )
                found.append(BlockError(unit.line, "quality-covers", message))
    return found


def bare_run_warnings(units: list[Unit], page_type: str) -> list[BlockError]:
    """On a recap, more than MAX_BARE_RUN blocks in a row without prose."""
    if page_type != "recap":
        return []
    found: list[BlockError] = []
    run = 0
    for unit in units:
        run = run + 1 if unit.kind == "block" else 0
        if run == MAX_BARE_RUN + 1:
            message = (
                f"more than {MAX_BARE_RUN} blocks in a row without prose; "
                "add a sentence that says what to read"
            )
            found.append(BlockError(unit.line, "quality-bare-run", message))
    return found


def quality_warnings(doc_text: str, task_ids: Collection[str] = ()) -> list[BlockError]:
    """Every quality warning in document order; `task_ids` are the plan's tasks."""
    fields, units = split_units(doc_text)
    found = first_block_warnings(units)
    found += stale_reference_warnings(units)
    found += open_choice_warnings(units)
    found += covers_warnings(units, task_ids)
    found += bare_run_warnings(units, fields.get("type", ""))
    return sorted(found, key=lambda warning: warning.line)
