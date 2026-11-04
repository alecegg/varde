"""The `include` statement: plan parts rendered into a page, from confined sources.

`<id> = include(source: "<path>", select: "<selector>", title: "<text>")` in a
`ui` fence names a `.md` file and a selector (see `select`). Allowed roots are
the page's own directory and the plan store (`<working>/plans/`). A source must
resolve (symlinks followed) to a regular `.md` file inside a root; `..`
segments, dotfiles and secret-like names are refused. The text is rendered by
the escape-first renderer, never inserted raw.
"""

from __future__ import annotations

import fnmatch
import html
import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from varde_learn.docs.pages.blocks.fences import find_fences
from varde_learn.docs.pages.blocks.include import include_faults
from varde_learn.docs.pages.lines import Statement, parse_lines
from varde_learn.docs.pages.select import (
    Selector,
    SelectorError,
    SourceBlock,
    parse_selector,
    read_source,
    region,
    select_blocks,
)
from varde_learn.docs.pages.template import make_read_only

MAX_SOURCE_BYTES = 1_000_000
_SECRET_NAMES = ("*.env*", "*secret*", "*credential*", "*token*")


class IncludeError(Exception):
    def __init__(self, line: int, reason: str) -> None:
        super().__init__(f"line {line}: {reason}")
        self.line = line
        self.reason = reason


@dataclass(frozen=True)
class IncludeRef:
    id: str
    source: str
    select: str
    title: str
    line: int  # 1-based document line of the statement


@dataclass(frozen=True)
class IncludeSource:
    """Where an include's text lives: the confined file and its selected lines."""

    path: Path
    start: int  # 0-based first source line
    end: int  # 0-based source line after the last


@dataclass(frozen=True)
class IncludedPart:
    id: str
    title: str
    source: IncludeSource
    markdown: str
    html: str
    nested: tuple[int, ...] = ()  # source lines of includes left unexpanded


# --- statements -------------------------------------------------------------


def _include_statements(text: str) -> Iterator[tuple[int, Statement]]:
    """Each `include` statement in the page's `ui` fences with its document line."""
    for fence in find_fences(text, frozenset({"ui"})):
        for statement in parse_lines(fence.body, partial=True).statements:
            if statement.component == "include":
                yield fence.line + statement.line, statement


def find_includes(text: str) -> list[IncludeRef]:
    """Every `include` statement on the page; raises IncludeError."""
    refs: list[IncludeRef] = []
    for line, statement in _include_statements(text):
        faults = include_faults(statement.props)
        if faults:
            raise IncludeError(line, faults[0].message)
        if any(ref.id == statement.id for ref in refs):
            raise IncludeError(line, f"include id '{statement.id}' is repeated")
        props = statement.props
        title = str(props.get("title", ""))
        refs.append(
            IncludeRef(
                statement.id, str(props["source"]), str(props["select"]), title, line
            )
        )
    return refs


# --- confinement ------------------------------------------------------------


@lru_cache(maxsize=8)
def default_plan_store(start: Path) -> Path:
    """`<working>/plans/` for the project holding `start`, resolved once per run."""
    from varde_core.memory_dirs import resolve_project_dir

    return resolve_project_dir(start, "working") / "plans"


def _roots(root: Path, store: Path | None) -> tuple[Path, ...]:
    plans = store if store is not None else default_plan_store(root.resolve())
    return (root.resolve(), plans.resolve())


def _refused_name(name: str) -> bool:
    lowered = name.lower()
    if lowered.startswith("."):
        return True
    return any(fnmatch.fnmatchcase(lowered, pattern) for pattern in _SECRET_NAMES)


def _raw_fault(raw: str) -> str | None:
    if not raw.strip() or "\x00" in raw:
        return "include source must be a path"
    parts = [
        part for part in raw.replace("\\", "/").split("/") if part not in {"", "."}
    ]
    if ".." in parts:
        return f"include source '{raw}' must not use '..'"
    if not Path(raw).is_absolute() and any(part.startswith(".") for part in parts):
        return f"include source '{raw}' names a dotfile or dot-directory"
    return None


def _confine(candidate: Path, roots: tuple[Path, ...], line: int) -> Path:
    shown = str(candidate)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise IncludeError(line, f"include source '{shown}' not found") from error
    home = next((root for root in roots if resolved.is_relative_to(root)), None)
    if home is None:
        raise IncludeError(
            line, f"include source '{shown}' is outside the allowed roots"
        )
    if any(_refused_name(part) for part in resolved.relative_to(home).parts):
        raise IncludeError(line, f"include source '{shown}' is not includable")
    if resolved.suffix != ".md" or not resolved.is_file():
        raise IncludeError(line, f"include source '{shown}' is not a .md file")
    return resolved


def _locate(ref: IncludeRef, root: Path, roots: tuple[Path, ...]) -> Path:
    fault = _raw_fault(ref.source)
    if fault:
        raise IncludeError(ref.line, fault)
    raw = Path(ref.source)
    path = _confine(raw if raw.is_absolute() else root / raw, roots, ref.line)
    selector = _selector(ref)
    if selector.kind != "task":
        return path
    return _confine(path.parent / "tasks" / f"{selector.arg}.md", roots, ref.line)


def _selector(ref: IncludeRef) -> Selector:
    try:
        return parse_selector(ref.select)
    except SelectorError as error:
        raise IncludeError(ref.line, str(error)) from error


def _read(path: Path, line: int) -> str:
    """Open once without following a final symlink; cap the bytes read."""
    name = path.name
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise IncludeError(line, f"include source '{name}' is unreadable") from error
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise IncludeError(line, f"include source '{name}' is not a .md file")
        data = handle.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise IncludeError(line, f"include source '{name}' is too large")
    return data.decode("utf-8", errors="replace")


# --- resolution -------------------------------------------------------------


def _resolve_one(
    ref: IncludeRef, root: Path, roots: tuple[Path, ...]
) -> tuple[Path, list[SourceBlock], str]:
    path = _locate(ref, root, roots)
    markdown = _read(path, ref.line)
    try:
        blocks = select_blocks(read_source(markdown), _selector(ref))
    except SelectorError as error:
        raise IncludeError(ref.line, str(error)) from error
    return path, blocks, markdown


def _resolve_all(
    text: str, root: Path, store: Path | None
) -> list[tuple[IncludeRef, Path, list[SourceBlock], str]]:
    roots = _roots(root, store)
    seen: set[tuple[Path, str]] = set()
    out = []
    for ref in find_includes(text):
        path, blocks, markdown = _resolve_one(ref, root, roots)
        key = (path, ref.select)
        if key in seen:
            raise IncludeError(ref.line, f"'{ref.source}' with '{ref.select}' repeats")
        seen.add(key)
        out.append((ref, path, blocks, markdown))
    return out


def include_sources(
    page_text: str, root: Path, store: Path | None = None
) -> dict[str, IncludeSource]:
    """Include id to its confined source and selected lines; raises IncludeError."""
    sources = {}
    for ref, path, blocks, _ in _resolve_all(page_text, root, store):
        start, end = region(blocks)
        sources[ref.id] = IncludeSource(path, start, end)
    return sources


def _part_html(ref: IncludeRef, blocks: list[SourceBlock]) -> str:
    part = html.escape(ref.id)
    out = [f'<section class="part" data-part="{part}">']
    if ref.title:
        out.append(f'<p class="part-title">{html.escape(ref.title)}</p>')
    for block in blocks:
        cls = "block heading" if block.kind == "heading" else "block"
        # ":" never occurs in a page block id, so the id cannot collide with one.
        dom_id = html.escape(f"blk-{ref.id}:{block.anchor}")
        attrs = (
            f'id="{dom_id}" data-anchor="{html.escape(block.anchor)}" '
            f'data-hash="{block.digest}" data-block-type="part" data-part="{part}"'
        )
        inner = make_read_only(block.html)
        out.append(f'<div class="{cls}" {attrs}>{inner}</div>')
    out.append("</section>")
    return "".join(out)


def resolve_includes(
    text: str, root: Path, store: Path | None = None
) -> dict[str, IncludedPart]:
    """Render each include; blocks carry their source anchor and the part id."""
    parts = {}
    for ref, path, blocks, markdown in _resolve_all(text, root, store):
        start, end = region(blocks)
        lines = read_source(markdown).lines
        nested = tuple(b.start + 1 for b in blocks if b.nested_include)
        parts[ref.id] = IncludedPart(
            ref.id,
            ref.title,
            IncludeSource(path, start, end),
            "\n".join(lines[start:end]),
            _part_html(ref, blocks),
            nested,
        )
    return parts


def include_errors(
    text: str, root: Path | None = None, store: Path | None = None
) -> list[tuple[int, str, str]]:
    """`(line, rule, message)` for the page's includes.

    Without `root` only statements are checked; with it each source and
    selector must resolve, and an include inside an included part is reported.
    """
    errors = [
        (line, fault.rule, fault.message)
        for line, statement in _include_statements(text)
        for fault in include_faults(statement.props)
    ]
    if errors or root is None:
        return errors
    try:
        parts = resolve_includes(text, root, store)
    except IncludeError as error:
        return [(error.line, "include", error.reason)]
    lines = {ref.id: ref.line for ref in find_includes(text)}
    return [
        (
            lines[part.id],
            "include-nested",
            f"'{part.id}' holds an include at source line {line}; not expanded",
        )
        for part in parts.values()
        for line in part.nested
    ]
