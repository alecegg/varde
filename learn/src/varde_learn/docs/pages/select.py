"""Pure plan-part selection: split a markdown source into anchored blocks, pick some.

Anchors follow the page renderer's scheme (`<heading-slug>`, `<slug>/<n>`, a
typed block's own id), so a comment anchored in a source keeps its place when
text outside the selected part changes. A heading may carry an explicit id
(`## Title {#my-id}`) that wins over its slug.

Selectors: `heading:<anchor>`, `task:<id>`, `frontmatter`, `acceptance`,
`lines:<a>-<b>` (1-based, inclusive; widened to whole blocks). `task:<id>` names
a file, not a region: the caller opens `tasks/<id>.md` beside the source and the
selector then selects all of it.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from varde_learn.docs.pages.blocks.include import (
    Selector,
    SelectorError,
    parse_selector,
)
from varde_learn.docs.pages.render import (
    _FENCE,
    _HEADING,
    PageCtx,
    _block_hash,
    _Part,
    _Scope,
    _unique_anchor,
    _unique_id_anchor,
    parse_blocks,
    render_inline,
    slugify,
    split_frontmatter,
    strip_comments,
)

HEADING_ID = re.compile(r"^[a-z0-9-]+$")
_EXPLICIT = re.compile(r"^(.*?)\s*\{#([a-z0-9-]+)\}\s*$")
_ID_MARK = re.compile(r"\{#([^{}\s]*)\}\s*$")
__all__ = [
    "Selector",
    "SelectorError",
    "SourceBlock",
    "SourceView",
    "heading_id_errors",
    "parse_selector",
    "read_source",
    "region",
    "select",
    "select_blocks",
]
_ACCEPTANCE = "acceptance criteria"
_INERT_LANGS = frozenset({"custom"})


@dataclass(frozen=True)
class SourceBlock:
    anchor: str
    kind: str  # heading, p, other, frontmatter
    level: int
    start: int  # 0-based source line of the first line
    end: int  # 0-based source line after the last non-blank line
    digest: str
    html: str  # inert: custom fences and nested includes render as plain code
    nested_include: bool = False


@dataclass(frozen=True)
class SourceView:
    lines: tuple[str, ...]
    frontmatter_end: int  # lines [0, n) are the frontmatter, fences included
    blocks: tuple[SourceBlock, ...]


def _fence_lang(source: str) -> str:
    match = _FENCE.match(source.split("\n", 1)[0])
    return match.group(3) if match else ""


def _inert_html(source: str, lang: str) -> str:
    cls = f' class="language-{html.escape(lang)}"' if lang else ""
    return f"<pre><code{cls}>{html.escape(source)}</code></pre>"


def _explicit_ids(parts: list[_Part]) -> set[str]:
    ids: set[str] = set()
    for part in parts:
        match = _EXPLICIT.match(part.text) if part.kind == "heading" else None
        if match:
            ids.add(match.group(2))
    return ids


def _block_html(part: _Part, explicit: bool) -> tuple[str, bool]:
    """Inner HTML for one part; the flag marks a nested `include` fence."""
    if part.kind == "heading" and explicit:
        title = _EXPLICIT.match(part.text)
        title_text = title.group(1) if title else part.text
        return f"<h{part.level}>{render_inline(title_text)}</h{part.level}>", False
    if part.kind == "include":  # an include statement is shown, not expanded
        return part.html, True
    lang = _fence_lang(part.source) if part.kind == "other" else ""
    if lang in _INERT_LANGS:
        return _inert_html(part.source, lang), False
    return part.html, False


def read_source(markdown: str) -> SourceView:
    lines = strip_comments(markdown.expandtabs(4).splitlines())
    _, content = split_frontmatter(lines)
    base = len(lines) - len(content)
    scope = _Scope(base, PageCtx("include"))
    parts = parse_blocks(content, scope=scope)
    reserved = _explicit_ids(parts)
    seen: dict[str, int] = {}
    taken: set[str] = set()
    section, count = "top", 0
    blocks: list[SourceBlock] = []
    for part in parts:
        explicit = _EXPLICIT.match(part.text) if part.kind == "heading" else None
        if part.kind == "heading":
            count = 0
            if explicit:
                section = _unique_id_anchor(explicit.group(2), taken)
            else:
                section = _unique_anchor(slugify(part.text), seen, taken | reserved)
            anchor = section
        else:
            count += 1
            anchor = f"{section}/{count}"
            if part.block_id:
                anchor = _unique_id_anchor(part.block_id, taken)
        taken.add(anchor)
        inner, nested = _block_html(part, explicit is not None)
        blocks.append(
            SourceBlock(
                anchor,
                part.kind,
                part.level,
                base + part.start,
                base + part.end,
                _block_hash(part.source),
                inner,
                nested,
            )
        )
    return SourceView(tuple(lines), base, tuple(blocks))


def _frontmatter_block(view: SourceView) -> SourceBlock:
    if not view.frontmatter_end:
        raise SelectorError("source has no frontmatter")
    text = "\n".join(view.lines[: view.frontmatter_end])
    digest = _block_hash(text)
    return SourceBlock(
        "top/0", "frontmatter", 0, 0, view.frontmatter_end, digest,
        _inert_html(text, "yaml"),
    )  # fmt: skip


def _section(view: SourceView, index: int) -> list[SourceBlock]:
    """The heading at `index` and its blocks to the next equal or higher heading."""
    blocks = view.blocks
    level = blocks[index].level
    end = index + 1
    while end < len(blocks) and not (
        blocks[end].kind == "heading" and blocks[end].level <= level
    ):
        end += 1
    return list(blocks[index:end])


def _by_anchor(view: SourceView, anchor: str) -> list[SourceBlock]:
    for index, block in enumerate(view.blocks):
        if block.anchor != anchor:
            continue
        return _section(view, index) if block.kind == "heading" else [block]
    raise SelectorError(f"no block with anchor '{anchor}' in the source")


def _acceptance(view: SourceView) -> list[SourceBlock]:
    for index, block in enumerate(view.blocks):
        title = _heading_title(view, block)
        if block.kind == "heading" and title.lower() == _ACCEPTANCE:
            return _section(view, index)
    raise SelectorError("source has no 'Acceptance criteria' heading")


def _heading_title(view: SourceView, block: SourceBlock) -> str:
    match = _HEADING.match(view.lines[block.start])
    title = match.group(2) if match else ""
    explicit = _EXPLICIT.match(title)
    return (explicit.group(1) if explicit else title).strip()


def _by_lines(view: SourceView, selector: Selector) -> list[SourceBlock]:
    first, last = selector.first - 1, selector.last  # 0-based half-open
    hit = [b for b in view.blocks if b.start < last and b.end > first]
    if not hit:
        raise SelectorError(f"lines {selector.first}-{selector.last} hold no block")
    return hit


def select_blocks(view: SourceView, selector: Selector) -> list[SourceBlock]:
    """The blocks a selector picks, in source order; raises SelectorError."""
    if selector.kind == "frontmatter":
        return [_frontmatter_block(view)]
    if selector.kind == "task":
        picked = list(view.blocks)
    elif selector.kind == "heading":
        picked = _by_anchor(view, selector.arg)
    elif selector.kind == "acceptance":
        picked = _acceptance(view)
    else:
        picked = _by_lines(view, selector)
    if not picked:
        raise SelectorError("source holds no blocks")
    return picked


def region(blocks: list[SourceBlock]) -> tuple[int, int]:
    """Source lines `[start, end)` that `blocks` cover."""
    return blocks[0].start, blocks[-1].end


def select(markdown: str, selector: str) -> str:
    """The selected part of `markdown` as markdown text; raises SelectorError."""
    view = read_source(markdown)
    start, end = region(select_blocks(view, parse_selector(selector)))
    return "\n".join(view.lines[start:end])


def heading_id_errors(markdown: str) -> list[tuple[int, str, str]]:
    """`(line, rule, message)` for explicit heading ids that are invalid or repeated."""
    errors: list[tuple[int, str, str]] = []
    first_seen: dict[str, int] = {}
    fence = ""
    for number, line in enumerate(markdown.expandtabs(4).splitlines(), 1):
        match = _FENCE.match(line)
        if match:
            marker = match.group(2)
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = ""
            continue
        mark = _ID_MARK.search(line) if not fence and _HEADING.match(line) else None
        if mark is None:
            continue
        ident = mark.group(1)
        if not HEADING_ID.match(ident):
            message = f"heading id '{ident}' must match {HEADING_ID.pattern}"
            errors.append((number, "heading-id-invalid", message))
        elif ident in first_seen:
            message = (
                f"heading id '{ident}' is already used at line {first_seen[ident]}"
            )
            errors.append((number, "heading-id-duplicate", message))
        else:
            first_seen[ident] = number
    return errors
