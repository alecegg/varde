"""Escape-first markdown subset to sanitized HTML. Pure functions, stdlib only."""

import hashlib
import html
import re
import textwrap
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field, replace

from varde_learn.docs.pages.actions import component_block_type
from varde_learn.docs.pages.blocks import CUSTOM_REMOVED
from varde_learn.docs.pages.blocks.change_summary import collect_markers
from varde_learn.docs.pages.blocks.check import (
    OLD_FENCES,
    TOML_FENCE_REMOVED,
    check_props,
)
from varde_learn.docs.pages.blocks_render import error_card, errors_card, render_block
from varde_learn.docs.pages.blocks_render.change_summary import render_change_summary
from varde_learn.docs.pages.blocks_render.code import render_code_panel
from varde_learn.docs.pages.blocks_render.file_tree import (
    code_titles,
    link_files,
    target_id,
)
from varde_learn.docs.pages.blocks_render.image import render_image, render_refused
from varde_learn.docs.pages.header import count_words, header_html
from varde_learn.docs.pages.lines import ParseError, Statement, parse_lines
from varde_learn.docs.pages.media import Media, Problem
from varde_learn.docs.pages.toc import toc_entries, toc_html


@dataclass(frozen=True)
class PageCtx:
    """What renderers may use besides their body; renderers never read files."""

    doc_name: str = ""
    parts: Mapping[str, str] = field(default_factory=dict)  # include id -> part HTML
    include_error: str = ""  # why no include could be resolved
    media: Mapping[str, Media | Problem] = field(default_factory=dict)  # image src
    export: bool = False  # a static export: images are inlined, not linked


# Fenced-block renderers keyed by the first info word; each returns trusted HTML.
# Signature: (body, block_id or None, line_offset, page_ctx). line_offset is the
# number of document lines before the body's first line, so body line k (1-based)
# is document line line_offset + k. A `ui` fence is split into statements instead.
BlockRenderer = Callable[[str, str | None, int, PageCtx], str]


def _custom_removed(
    body: str, block_id: str | None, line_offset: int, ctx: PageCtx
) -> str:
    """A stored `custom` fence is no longer run; show a plain error card."""
    return error_card("custom block removed", [CUSTOM_REMOVED])


def _old_fence_removed(lang: str) -> BlockRenderer:
    message = f"`{lang}` fence: {TOML_FENCE_REMOVED}"
    return lambda body, block_id, line_offset, ctx: error_card(
        "toml-fence-removed", [message]
    )


BLOCKS: dict[str, BlockRenderer] = {
    "custom": _custom_removed,
    **{lang: _old_fence_removed(lang) for lang in sorted(OLD_FENCES)},
}

_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([\w-]*)(.*)")
_BLOCK_ID = re.compile(r"^id=([a-z][a-z0-9-]{0,47})$")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_MARKER = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_TASK = re.compile(r"^\[([ xX])\]\s+")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
# Inline spans are length-bounded so pathological input stays linear-ish.
_LINK = re.compile(
    r"\[([^\]\n]{1,300})\]\(([^)\s]{0,2000})"
    r"(?:\s+(?:&quot;(.{0,300}?)&quot;|&#x27;(.{0,300}?)&#x27;))?\)"
)
_BOLD = re.compile(r"\*\*(?=\S)(.{1,500}?)(?<=\S)\*\*")
_EMPHASIS = re.compile(r"(?<![\w*])\*(?=[^\s*])(.{1,500}?)(?<=[^\s*])\*(?!\*)")
_UNDERSCORE = re.compile(r"(?<![\w_])_(?=[^\s_])(.{1,500}?)(?<=[^\s_])_(?![\w_])")
_MAX_DEPTH = 20  # block nesting beyond this renders as plain text
_SAFE_URL = re.compile(
    r"^(https?://[A-Za-z0-9\-._~:/?#\[\]@!$&()*+,;=%]+|#[A-Za-z0-9\-._~:/?#%]*)$"
)
_TOKEN = re.compile("\x00(\\d+)\x00")
_TAG = re.compile(r"<[^>]*>")
_STATUS_KEYS = ("type", "status", "risk", "status_at")


@dataclass(frozen=True)
class PageBlock:
    anchor: str
    hash: str
    text: str  # first 80 visible characters, used as the comment quote
    block_type: str = "prose"
    start: int = 0  # document line (0-based) of the block's first source line
    end: int = 0  # document line after its last non-blank source line


@dataclass(frozen=True)
class RenderedPage:
    body: str
    status: str
    blocks: tuple[PageBlock, ...]


@dataclass(frozen=True)
class _Scope:
    base: int  # document line number (0-based) of the first line being parsed
    ctx: PageCtx


@dataclass(frozen=True)
class _Part:
    # heading, p, other, include (shown, not expanded), raw (HTML as is, no wrapper)
    kind: str
    html: str
    source: str
    level: int = 0
    text: str = ""
    block_id: str | None = None  # set for typed blocks fenced with a valid id
    start: int = 0  # line index in the parsed list where the block begins
    end: int = 0  # line index after its last non-blank line
    children: tuple[_Part, ...] = ()  # a `ui` fence: one part per statement
    block_type: str = "prose"  # prose, heading, list, table, code, part, error, ...
    component: str = ""  # a `ui` statement's component name
    props: Mapping[str, object] = field(default_factory=dict)  # its parsed props


# --- inline -----------------------------------------------------------------


def classify_url(url: str) -> str:
    """Return 'link' (http, https, #), 'relative', or 'text' (any other scheme)."""
    stripped = re.sub(r"[\s\x00-\x1f\x7f]", "", html.unescape(url))
    if _SAFE_URL.match(url) and stripped == url:
        return "link"
    if not stripped or stripped.startswith(("//", "\\")) or "\\" in stripped:
        return "text"
    head = re.split(r"[/?#]", stripped, maxsplit=1)[0]
    return "text" if ":" in head or not stripped.isascii() else "relative"


def _render_link(text: str, raw_url: str, title: str) -> str:
    url = html.unescape(raw_url)
    kind = classify_url(url)
    if kind == "link":
        attrs = f' title="{title}"' if title else ""
        return (
            f'<a href="{html.escape(url)}" rel="noopener noreferrer"{attrs}>{text}</a>'
        )
    if kind == "relative":
        return f'<span class="relative-link" title="{html.escape(url)}">{text}</span>'
    return text


def render_inline(text: str) -> str:
    """Escape first, then apply code, links, bold and emphasis on the escaped text."""
    stash: list[str] = []

    def keep(fragment: str) -> str:
        stash.append(fragment)
        return f"\x00{len(stash) - 1}\x00"

    def code(match: re.Match[str]) -> str:
        return keep(f"<code>{html.escape(match.group(1))}</code>")

    def link(match: re.Match[str]) -> str:
        title = _TOKEN.sub("", match.group(3) or match.group(4) or "")
        label = _emphasis(match.group(1))
        return keep(_render_link(label, match.group(2), title))

    text = text.replace("\x00", "")
    text = _CODE_SPAN.sub(code, text)
    escaped = html.escape(text)
    escaped = _LINK.sub(link, escaped)
    escaped = _emphasis(escaped)
    return _restore(escaped, stash)


def _emphasis(escaped: str) -> str:
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    escaped = _EMPHASIS.sub(r"<em>\1</em>", escaped)
    return _UNDERSCORE.sub(r"<em>\1</em>", escaped)


def _restore(text: str, stash: list[str]) -> str:
    # Stashed fragments may themselves hold tokens (link labels), so loop.
    def fragment(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return stash[index] if index < len(stash) else ""

    for _ in range(len(stash) + 1):
        if not _TOKEN.search(text):
            break
        text = _TOKEN.sub(fragment, text)
    return _TOKEN.sub("", text)


# --- preprocessing ----------------------------------------------------------


def strip_comments(lines: list[str]) -> list[str]:
    """Drop HTML comments outside fenced code."""
    out: list[str] = []
    fence = ""
    in_comment = False
    for line in lines:
        match = _FENCE.match(line)
        if fence:
            fence = (
                ""
                if match
                and match.group(2)[0] == fence[0]
                and len(match.group(2)) >= len(fence)
                else fence
            )
            out.append(line)
        elif match and not in_comment:
            fence = match.group(2)
            out.append(line)
        else:
            stripped, in_comment = _strip_line(line, in_comment)
            out.append(stripped)
    return out


_CODE_RUN = re.compile(r"`+")


def _strip_line(line: str, in_comment: bool) -> tuple[str, bool]:
    kept: list[str] = []
    pos = 0
    while pos < len(line):
        if in_comment:
            end = line.find("-->", pos)
            if end < 0:
                return "".join(kept), True
            pos, in_comment = end + 3, False
            continue
        start = line.find("<!--", pos)
        span = _CODE_RUN.search(line, pos, start if start >= 0 else len(line))
        if span:
            close = line.find(span.group(), span.end())
            end = close + len(span.group()) if close >= 0 else span.end()
            kept.append(line[pos:end])
            pos = end
            continue
        if start < 0:
            kept.append(line[pos:])
            break
        kept.append(line[pos:start])
        pos, in_comment = start + 4, True
    return "".join(kept), in_comment


def split_frontmatter(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    if not lines or lines[0].strip() != "---":
        return {}, lines
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            return _frontmatter_fields(lines[1:end]), lines[end + 1 :]
    return {}, lines


def _frontmatter_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in lines:
        key, sep, value = line.partition(":")
        if sep and key.strip() and not line.startswith((" ", "\t", "#", "-")):
            fields[key.strip()] = value.strip().strip("\"'")
    return fields


def status_line(fields: dict[str, str]) -> str:
    parts = [f"{key}: {fields[key]}" for key in _STATUS_KEYS if fields.get(key)]
    return " · ".join(parts)


# --- blocks -----------------------------------------------------------------


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_table_start(lines: list[str], i: int) -> bool:
    return (
        "|" in lines[i]
        and i + 1 < len(lines)
        and "-" in lines[i + 1]
        and bool(_TABLE_SEP.match(lines[i + 1]))
    )


def _starts_block(lines: list[str], i: int) -> bool:
    line = lines[i]
    named = (_FENCE, _HEADING, _HR, _QUOTE, _MARKER)
    return any(p.match(line) for p in named) or _is_table_start(lines, i)


def parse_blocks(
    lines: list[str], depth: int = 0, scope: _Scope | None = None
) -> list[_Part]:
    scope = scope or _Scope(0, PageCtx())
    if depth > _MAX_DEPTH:
        text = " ".join(line.strip() for line in lines if line.strip())
        return [_Part("p", f"<p>{html.escape(text)}</p>", "\n".join(lines), text=text)]
    parts: list[_Part] = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        first = i
        part, i = _parse_one(lines, i, depth, scope)
        if part.children:  # statement parts carry their own line spans
            parts.extend(part.children)
            continue
        last = i
        while last > first + 1 and not lines[last - 1].strip():
            last -= 1
        parts.append(replace(part, start=first, end=last))
    return parts


def _parse_one(
    lines: list[str], i: int, depth: int, scope: _Scope
) -> tuple[_Part, int]:
    line = lines[i]
    if _FENCE.match(line):
        return _parse_fence(lines, i, scope)
    heading = _HEADING.match(line)
    if heading:
        level, text = len(heading.group(1)), heading.group(2)
        return _Part(
            "heading",
            f"<h{level}>{render_inline(text)}</h{level}>",
            line,
            level,
            text,
            block_type="heading",
        ), i + 1
    if _HR.match(line):
        return _Part("other", "<hr>", line), i + 1
    if _is_table_start(lines, i):
        return _parse_table(lines, i)
    if _QUOTE.match(line):
        return _parse_quote(lines, i, depth, scope)
    if _MARKER.match(line):
        return _parse_list(lines, i, depth, scope)
    return _parse_paragraph(lines, i)


def _parse_fence(lines: list[str], i: int, scope: _Scope) -> tuple[_Part, int]:
    opening = _FENCE.match(lines[i])
    if opening is None:
        raise ValueError(lines[i])
    indent, fence, lang = len(opening.group(1)), opening.group(2), opening.group(3)
    block_id = _info_id(opening.group(4))
    body: list[str] = []
    j = i + 1
    while j < len(lines):
        closing = _FENCE.match(lines[j])
        if (
            closing
            and closing.group(2)[0] == fence[0]
            and len(closing.group(2)) >= len(fence)
            and not closing.group(3)
        ):
            j += 1
            break
        body.append(lines[j][min(indent, _indent(lines[j])) :])
        j += 1
    content = "\n".join(body)
    source = "\n".join(lines[i:j])
    if lang == "ui":
        return _ui_fence(content, lines, (i, j), scope), j
    if lang in BLOCKS:
        offset = scope.base + i + 1
        html_ = BLOCKS[lang](content, block_id, offset, scope.ctx)
        return _Part("other", html_, source, block_id=block_id, block_type="error"), j
    return _Part(
        "other", render_code_panel(content, lang), source, block_type="code"
    ), j


def _statement_html(
    statement: Statement, line: int, source: str, ctx: PageCtx
) -> tuple[str, str, str]:
    """(kind, HTML, block type) of one statement; `line` is its document line."""
    if statement.component == "image":
        return "other", _image_html(statement, line, ctx), component_block_type("image")
    if statement.component != "include":
        html_ = render_block(statement.component, statement.props, statement.id, line)
        return "other", html_, component_block_type(statement.component)
    errors = [e.text() for e in check_props("include", statement.props, line)]
    if errors:
        return "other", errors_card("include", errors), "error"
    if ctx.include_error:
        return "other", errors_card("include", [ctx.include_error]), "error"
    part = ctx.parts.get(statement.id)
    if part is None:  # inside an included source, or a page without a resolver
        shown = html.escape(source)
        return "include", f'<pre><code class="language-ui">{shown}</code></pre>', "part"
    return "raw", part, "part"


def _image_html(statement: Statement, line: int, ctx: PageCtx) -> str:
    """The figure for an `image` statement; a refused file is an error card."""
    props = statement.props
    errors = [e.text() for e in check_props("image", props, line)]
    if errors:
        return render_refused(props, errors)
    media = ctx.media.get(str(props.get("src")))
    if isinstance(media, Problem):
        return render_refused(props, [media.reason])
    if media is None:  # inside an included source: no directory to read from
        return render_block("image", props, statement.id, line)
    return render_image(props, media, export=ctx.export)


def _ui_fence(
    content: str, lines: list[str], span: tuple[int, int], scope: _Scope
) -> _Part:
    """One part per statement of a `ui` fence, plus one error card for parse errors."""
    first, end = span
    offset = scope.base + first + 1
    result = parse_lines(content)
    children: list[_Part] = []
    for statement in result.statements:
        start, stop = first + statement.line, first + statement.end_line + 1
        source = "\n".join(lines[start:stop])
        line = offset + statement.line
        kind, html_, block_type = _statement_html(statement, line, source, scope.ctx)
        children.append(
            _Part(
                kind,
                html_,
                source,
                block_id=statement.id,
                start=start,
                end=stop,
                block_type=block_type,
                component=statement.component,
                props=statement.props,
            )
        )
    if result.errors:
        card_ = errors_card(
            "ui", [e.text() for e in _document_errors(result.errors, offset)]
        )
        fence_source = "\n".join(lines[first:end])
        children.append(
            _Part(
                "other", card_, fence_source, start=first, end=end, block_type="error"
            )
        )
    if not children:  # an opened fence with no statement yet shows nothing
        return _Part("raw", "", "\n".join(lines[first:end]))
    return _Part("other", "", "", children=tuple(children))


def _document_errors(errors: list[ParseError], offset: int) -> list[ParseError]:
    return [ParseError(offset + e.line, e.rule, e.message) for e in errors]


def _info_id(rest: str) -> str | None:
    """Return the slug of an `id=<slug>` word in the info string rest, if valid."""
    for word in rest.split():
        match = _BLOCK_ID.match(word)
        if match:
            return match.group(1)
    return None


def _split_row(row: str) -> list[str]:
    spans: list[str] = []

    def mask(match: re.Match[str]) -> str:
        spans.append(match.group(0))
        return f"\x00{len(spans) - 1}\x00"

    masked = _CODE_SPAN.sub(mask, row.replace("\x00", "").strip())
    masked = masked.removeprefix("|").removesuffix("|")
    cells = re.split(r"(?<!\\)\|", masked)
    return [_restore(cell.strip().replace("\\|", "|"), spans) for cell in cells]


def _alignment(cell: str) -> str:
    cell = cell.strip()
    if cell.startswith(":") and cell.endswith(":"):
        return "center"
    return "right" if cell.endswith(":") else ""


def _parse_table(lines: list[str], i: int) -> tuple[_Part, int]:
    header = _split_row(lines[i])
    aligns = [_alignment(c) for c in _split_row(lines[i + 1])]
    j = i + 2
    rows: list[list[str]] = []
    while j < len(lines) and lines[j].strip() and "|" in lines[j]:
        rows.append(_split_row(lines[j]))
        j += 1

    def cell(tag: str, index: int, text: str) -> str:
        align = aligns[index] if index < len(aligns) and aligns[index] else ""
        cls = f' class="align-{align}"' if align else ""
        return f"<{tag}{cls}>{render_inline(text)}</{tag}>"

    head = "".join(cell("th", n, c) for n, c in enumerate(header))
    body = "".join(
        "<tr>" + "".join(cell("td", n, c) for n, c in enumerate(r)) + "</tr>"
        for r in rows
    )
    table = (
        '<div class="scroll"><table>'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )
    return _Part("other", table, "\n".join(lines[i:j]), block_type="table"), j


def _parse_quote(
    lines: list[str], i: int, depth: int, scope: _Scope
) -> tuple[_Part, int]:
    j = i
    inner: list[str] = []
    while j < len(lines) and _QUOTE.match(lines[j]):
        inner.append(re.sub(r"^\s{0,3}> ?", "", lines[j]))
        j += 1
    inner_scope = _Scope(scope.base + i, scope.ctx)
    content = "".join(p.html for p in parse_blocks(inner, depth + 1, inner_scope))
    return _Part(
        "other", f"<blockquote>{content}</blockquote>", "\n".join(lines[i:j])
    ), j


def _parse_paragraph(lines: list[str], i: int) -> tuple[_Part, int]:
    j = i + 1
    while j < len(lines) and lines[j].strip() and not _starts_block(lines, j):
        j += 1
    text = " ".join(line.strip() for line in lines[i:j])
    return _Part(
        "p", f"<p>{render_inline(text)}</p>", "\n".join(lines[i:j]), text=text
    ), j


def _item_end(lines: list[str], j: int, indent: int) -> bool:
    """True when line j does not belong to a list item whose marker has `indent`."""
    line = lines[j]
    if line.strip():
        return _indent(line) <= indent
    following = next((n for n in lines[j + 1 :] if n.strip()), None)
    return following is None or _indent(following) <= indent


def _parse_list(
    lines: list[str], i: int, depth: int, scope: _Scope
) -> tuple[_Part, int]:
    first = _MARKER.match(lines[i])
    if first is None:
        raise ValueError(lines[i])
    indent, ordered = len(first.group(1)), first.group(2)[0].isdigit()
    start = int(first.group(2)[:-1]) if ordered else 1
    items: list[str] = []
    j = i
    while j < len(lines):
        marker = _MARKER.match(lines[j])
        if not marker or len(marker.group(1)) != indent:
            break
        if marker.group(2)[0].isdigit() != ordered:
            break
        k = j + 1
        while k < len(lines) and not _item_end(lines, k, indent):
            k += 1
        item_scope = _Scope(scope.base + j, scope.ctx)
        items.append(_render_item(marker.group(3), lines[j + 1 : k], depth, item_scope))
        j = k
        while j < len(lines) and not lines[j].strip():
            j += 1
    tag = "ol" if ordered else "ul"
    attr = f' start="{start}"' if ordered and start != 1 else ""
    return _Part(
        "other",
        f"<{tag}{attr}>{''.join(items)}</{tag}>",
        "\n".join(lines[i:j]).rstrip(),
        block_type="list",
    ), j


def _render_item(first: str, rest: list[str], depth: int, scope: _Scope) -> str:
    task = _TASK.match(first)
    prefix = ""
    if task:
        first = first[task.end() :]
        checked = task.group(1) != " "
        cls, mark = ("task done", "☑") if checked else ("task", "☐")
        prefix = f'<span class="{cls}">{mark}</span> '
    body = [first, *textwrap.dedent("\n".join(rest)).split("\n")] if rest else [first]
    parts = parse_blocks(body, depth + 1, scope)
    rendered = []
    for n, part in enumerate(parts):
        if n == 0 and part.kind == "p":
            rendered.append(part.html.removeprefix("<p>").removesuffix("</p>"))
        else:
            rendered.append(part.html)
    return f"<li>{prefix}{''.join(rendered)}</li>"


# --- page -------------------------------------------------------------------


def slugify(text: str) -> str:
    plain = re.sub(r"[`*_]", "", text).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")
    if slug:
        return slug
    return "section-" + hashlib.sha256(plain.encode("utf-8")).hexdigest()[:6]


def plain_text(fragment: str, limit: int = 80) -> str:
    text = html.unescape(_TAG.sub(" ", fragment))
    return " ".join(text.split())[:limit]


def _block_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]


def _wrap(
    anchor: str, digest: str, inner: str, block_type: str, cls: str = "block"
) -> str:
    attrs = (
        f'id="{html.escape(target_id(anchor))}" data-anchor="{html.escape(anchor)}" '
        f'data-hash="{digest}" data-block-type="{html.escape(block_type)}"'
    )
    return f'<div class="{cls}" {attrs}>{inner}</div>'


def _unique_anchor(slug: str, seen: dict[str, int], taken: set[str]) -> str:
    """Return slug, or slug-N for the first unused N, and record it as used."""
    candidate = slug
    while candidate in seen or candidate in taken:
        seen[slug] = seen.get(slug, 1) + 1
        candidate = f"{slug}-{seen[slug]}"
    seen.setdefault(candidate, 1)
    return candidate


def _unique_id_anchor(
    block_id: str, taken: set[str], reserved: Collection[str] = ()
) -> str:
    """The id, or id-N for the first N used by no anchor and no other statement id."""
    candidate, n = block_id, 1
    while candidate in taken or (n > 1 and candidate in reserved):
        n += 1
        candidate = f"{block_id}-{n}"
    return candidate


def _fill_change_summaries(parts: list[_Part]) -> list[_Part]:
    """Give each valid `change-summary` the markers of the page's parsed statements."""
    if not any(part.component == "change-summary" for part in parts):
        return parts
    markers = collect_markers((p.component, p.props) for p in parts if p.component)
    return [
        replace(part, html=render_change_summary(dict(part.props), markers))
        if part.component == "change-summary"
        and not check_props(part.component, dict(part.props), 0)
        else part
        for part in parts
    ]


def render_page(
    markdown: str, doc_name: str, ctx: PageCtx | None = None
) -> RenderedPage:
    lines = strip_comments(markdown.expandtabs(4).splitlines())
    fields, content = split_frontmatter(lines)
    status = status_line(fields)
    header = header_html(fields, doc_name, count_words(content))
    pieces = [header]
    blocks: list[PageBlock] = []
    seen: dict[str, int] = {}
    taken: set[str] = set()
    titles: dict[str, str] = {}  # code block title -> anchor, for file-tree links
    section, count = "top", 0
    headings: list[tuple[int, str, str]] = []
    scope = _Scope(len(lines) - len(content), ctx or PageCtx(doc_name))
    parts = _fill_change_summaries(parse_blocks(content, scope=scope))
    reserved = {part.block_id for part in parts if part.block_id}
    for part in parts:
        if part.kind == "raw":
            pieces.append(part.html)
            count += bool(part.block_id)  # an include counts as it does unresolved
            continue
        digest = _block_hash(part.source)
        if part.kind == "heading":
            section = _unique_anchor(slugify(part.text), seen, taken | reserved)
            count = 0
            headings.append((part.level, plain_text(part.html, 120), section))
            anchor, inner = section, part.html.replace(">", f' id="h-{section}">', 1)
            cls = "block heading"
        else:
            count += 1
            anchor, inner, cls = f"{section}/{count}", part.html, "block"
            if part.block_id:
                anchor = _unique_id_anchor(part.block_id, taken, reserved)
        taken.add(anchor)
        file_titles = code_titles(part.html)
        for file_title in file_titles:
            titles.setdefault(file_title, anchor)
        pieces.append(_wrap(anchor, digest, inner, part.block_type, cls))
        first, last = scope.base + part.start, scope.base + part.end
        blocks.append(
            PageBlock(
                anchor, digest, plain_text(part.html), part.block_type, first, last
            )
        )
    toc = toc_html(toc_entries(headings))
    if toc:
        pieces.insert(1, toc)
    pieces = [link_files(p, titles) if "vd-file-tree-leaf" in p else p for p in pieces]
    return RenderedPage("\n".join(pieces), status, tuple(blocks))
