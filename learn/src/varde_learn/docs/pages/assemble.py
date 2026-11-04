"""Assemble one served or exported page: parse, render, wrap in the host shell."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from varde_learn.docs.pages.blocks_render.containers import fill_containers
from varde_learn.docs.pages.comments import fold, read_rows
from varde_learn.docs.pages.include import (
    IncludeError,
    find_includes,
    resolve_includes,
)
from varde_learn.docs.pages.lines import parse_lines
from varde_learn.docs.pages.media import page_media
from varde_learn.docs.pages.render import (
    _FENCE,
    PageCtx,
    RenderedPage,
    render_page,
    strip_comments,
)
from varde_learn.docs.pages.template import make_read_only, page_shell


def render_thread(comment: dict[str, Any], orphan: bool) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value))

    classes = "thread" + (" orphan" if orphan else "")
    if comment.get("state") == "resolved":
        classes += " resolved"

    def meta(row: dict[str, Any]) -> str:
        return (
            f'<p class="meta">{esc(row.get("actor", ""))} {esc(row.get("ts", ""))}</p>'
        )

    def text(row: dict[str, Any]) -> str:
        return f'<p class="text">{esc(row.get("text", ""))}</p>'

    anchor = esc(comment.get("anchor", ""))
    kind = esc(comment.get("kind", "comment"))
    cid = esc(comment.get("id", ""))
    open_tag = (
        f'<article class="{classes}" data-anchor="{anchor}" '
        f'data-id="{cid}" data-kind="{kind}">'
    )
    parts = [open_tag]
    if orphan and comment.get("quote"):
        parts.append(f"<blockquote>{esc(comment['quote'])}</blockquote>")
    parts += [meta(comment), text(comment)]
    if comment.get("kind") == "suggestion":
        parts.append(
            f'<p class="suggestion"><del>{esc(comment.get("quote", ""))}</del> '
            f"<ins>{esc(comment.get('replacement', ''))}</ins></p>"
        )
        if comment.get("applied_by"):
            parts.append(f'<p class="meta">applied by {esc(comment["applied_by"])}</p>')
    parts += [
        f'<div class="reply">{meta(r)}{text(r)}</div>'
        for r in comment.get("replies", [])
    ]
    parts.append("</article>")
    return "".join(parts)


def render_threads(page: RenderedPage, comments: list[dict[str, Any]]) -> str:
    anchors = {block.anchor for block in page.blocks}
    placed = [c for c in comments if c.get("anchor") in anchors]
    orphans = [c for c in comments if c.get("anchor") not in anchors]
    out = [render_thread(c, orphan=False) for c in placed]
    if orphans:
        out.append('<section class="orphans"><h2>Comments on edited text</h2>')
        out.extend(render_thread(c, orphan=True) for c in orphans)
        out.append("</section>")
    return "".join(out)


def read_markdown(doc: Path) -> str:
    try:
        return doc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"# Unreadable\n\n{doc.name} could not be read."


def fill_page(page: RenderedPage) -> RenderedPage:
    """The page with each container's held blocks moved into its panels."""
    return replace(page, body=fill_containers(page.body))


def parse_page(text: str, doc_name: str, ctx: PageCtx | None = None) -> RenderedPage:
    """The strict parse entry point for served and exported pages."""
    return fill_page(render_page(text, doc_name, ctx))


def _open_fence(lines: list[str]) -> tuple[int, re.Match[str]] | None:
    """The unclosed fence at the end of `lines`, by the renderer's fence rules."""
    opener: tuple[int, re.Match[str]] | None = None
    for i, line in enumerate(lines):
        match = _FENCE.match(line)
        if match is None:
            continue
        if opener is None:
            opener = (i, match)
            continue
        fence = opener[1].group(2)
        closes = (
            match.group(2)[0] == fence[0]
            and len(match.group(2)) >= len(fence)
            and not match.group(3)
        )
        if closes:
            opener = None
    return opener


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def drop_pending_tail(text: str) -> str:
    """Cut a half-written trailing `ui` fence back to its complete statements.

    Complete text is returned unchanged; a cut text is normalised to the
    renderer's own line view (tabs expanded, comments stripped, `\\n` ends).
    """
    lines = strip_comments(text.expandtabs(4).splitlines())
    found = _open_fence(lines)
    if found is None or found[1].group(3) != "ui":
        return text
    at, opening = found
    indent = len(opening.group(1))
    body = [
        line[min(indent, len(line) - len(line.lstrip())) :] for line in lines[at + 1 :]
    ]
    pending = parse_lines("\n".join(body), partial=True).pending
    if not pending:
        return text
    kept = "\n".join(body)[: -len(pending)]
    kept_lines = lines[at + 1 : at + 1 + kept.count("\n")]
    return "\n".join([*lines[: at + 1], *kept_lines, opening.group(2)]) + "\n"


def parse_page_stream(
    text: str, doc_name: str, ctx: PageCtx | None = None
) -> RenderedPage:
    """Parse a half-written page: an unfinished `ui` statement renders as nothing."""
    return fill_page(render_page(drop_pending_tail(text), doc_name, ctx))


def include_ctx(
    text: str, doc: Path, *, export: bool = False
) -> tuple[PageCtx, dict[str, Path]]:
    """The render context holding each include's part HTML, and its source paths.

    It also holds the page's image files (inlined when `export`).
    """
    whole = drop_pending_tail(text)
    media = page_media(whole, doc, embed=export)
    try:
        parts = resolve_includes(whole, doc.parent) if find_includes(whole) else {}
    except IncludeError as error:
        return PageCtx(
            doc.name, include_error=str(error), media=media, export=export
        ), {}
    shown = {name: part.html for name, part in parts.items()}
    ctx = PageCtx(doc.name, shown, media=media, export=export)
    return ctx, {name: part.source.path for name, part in parts.items()}


@dataclass(frozen=True)
class AssembledPage:
    html: str
    # include id -> confined source path; filled once `include` statements exist
    parts: dict[str, Path] = field(default_factory=dict)


def assemble(doc: Path, *, token: str) -> AssembledPage:
    text = read_markdown(doc)
    ctx, sources = include_ctx(text, doc)
    page = parse_page_stream(text, doc.name, ctx)
    threads = render_threads(page, fold(read_rows(doc)))
    main = f'<main data-role="page">{page.body}{threads}</main>'
    return AssembledPage(page_shell(doc.name, main, token), sources)


def assemble_page(doc: Path, *, token: str) -> str:
    """Full served HTML for `doc`."""
    return assemble(doc, token=token).html


def assemble_static(doc: Path) -> str:
    """Self-contained export: no script, token or comments; inputs read-only."""
    text = read_markdown(doc)
    page = parse_page(text, doc.name, include_ctx(text, doc, export=True)[0])
    main = f'<main data-role="page">{make_read_only(page.body)}</main>'
    return page_shell(doc.name, main, None)
