"""HTML for tabs and columns: panels with empty slots, filled by the page assembler.

A container renders as a panel skeleton; each slot names a held block id.
`fill_containers` moves the already-rendered held blocks into the slots, so a held
block is rendered once and keeps its own id and action menu. Every panel shows by
default (headings label them); `containers.js` turns tab panels into a tablist.
"""

import hashlib
import html
import re

from varde_learn.docs.pages.blocks.containers import HOLD_KEYS
from varde_learn.docs.pages.blocks_render.common import as_dict, as_list, esc
from varde_learn.docs.pages.blocks_render.svg import copy_attr

_ROOT = re.compile(
    r'<div class="block" id="blk-([a-z0-9-]+)" data-anchor="[^"]*" '
    r'data-hash="([0-9a-f]+)" data-block-type="visual">'
    r'<section class="vb (tabs|columns) vd-containers[^"]*" aria-label="[^"]*" '
    r'data-copy="">'
)
_SLOT = re.compile(r'<div class="vd-containers-slot" data-hold="([a-z0-9-]*)"></div>')
_DIV = re.compile(r"<div\b|</div>")
_COPY = re.compile(r' data-copy="([^"]*)"')
_TAG = re.compile(r"<[^>]*>")
_INPUT_TYPES = frozenset({"widget", "decision"})


def _slots(held: list[object]) -> str:
    return "".join(
        f'<div class="vd-containers-slot" data-hold="{esc(h)}"></div>' for h in held
    )


def _panel(prefix: str, n: int, panel: dict[str, object], cls: str) -> str:
    label = panel.get("label")
    head_id = f"{prefix}-{n}-h"
    heading = (
        f'<h4 class="vd-containers-label" id="{head_id}">{esc(label)}</h4>'
        if label
        else ""
    )
    name = f' aria-labelledby="{head_id}"' if label else f' aria-label="Column {n}"'
    slots = _slots(as_list(panel.get("blocks")))
    return (
        f'<section class="vd-containers-panel {cls}"{name}>{heading}{slots}</section>'
    )


def _render(kind: str, props: dict[str, object], block_id: str | None) -> str:
    panels = [as_dict(p) for p in as_list(props.get(HOLD_KEYS[kind]))]
    prefix = f"vd-c{kind[:3]}-{block_id or 'x'}"
    panel_cls = "vd-ctabs-panel" if kind == "tabs" else "vd-columns-panel"
    inner = "".join(_panel(prefix, n, p, panel_cls) for n, p in enumerate(panels, 1))
    if kind == "columns":
        inner = f'<div class="vd-columns-grid vd-columns-n{len(panels)}">{inner}</div>'
    cls = f"vb {kind} vd-containers vd-{'ctabs' if kind == 'tabs' else 'columns'}"
    label = kind.title()
    noun = "tab" if kind == "tabs" else "column"
    names = ", ".join(str(p["label"]) for p in panels if p.get("label"))
    count = f"{len(panels)} {noun}{'' if len(panels) == 1 else 's'}"
    text = esc(f"{count}: {names}" if names else count)
    alt = f'<p class="vb-alt vd-containers-alt">{text}</p>'
    return (
        f'<section class="{cls}" aria-label="{label}" data-copy="">'
        f"{alt}{inner}</section>"
    )


def render_tabs(props: dict[str, object], block_id: str | None) -> str:
    return _render("tabs", props, block_id)


def render_columns(props: dict[str, object], block_id: str | None) -> str:
    return _render("columns", props, block_id)


# --- filling ----------------------------------------------------------------


def _block_start(body: str, ident: str) -> int:
    return body.find(f'<div class="block" id="blk-{ident}" ')


def _block_end(body: str, start: int) -> int:
    """Index after the `</div>` closing the block that opens at `start`."""
    depth = 0
    for tag in _DIV.finditer(body, start):
        depth += 1 if tag.group().startswith("<div") else -1
        if depth == 0:
            return tag.end()
    return len(body)


def _copy_of(block: str) -> str:
    marked = _COPY.search(block)
    if marked:
        return html.unescape(marked.group(1))
    return " ".join(html.unescape(_TAG.sub(" ", block)).split())


def _note(text: str) -> str:
    return f'<p class="vd-containers-note">{esc(text)}</p>'


def _take(body: str, held: str, kind: str, taken: set[str]) -> tuple[str, str, str]:
    """(body without the held block, its HTML or a note, its copy text)."""
    start = _block_start(body, held)
    if start >= 0 and held in taken:
        start = -1
    if start < 0:
        return (
            body,
            _note(f"Block '{held}' is missing, held elsewhere, or is this container."),
            "",
        )
    end = _block_end(body, start)
    block = body[start:end]
    if " vd-containers" in block[:600]:
        return (
            body,
            _note(f"Block '{held}' is a container; containers do not nest."),
            "",
        )
    if kind == "tabs" and any(
        f'data-block-type="{t}"' in block[:300] for t in _INPUT_TYPES
    ):
        return body, _note(f"Input '{held}' cannot be held in tabs."), ""
    taken.add(held)
    return body[:start] + body[end:], block, _copy_of(block)


_LABEL = re.compile(r'class="vd-containers-label" id="[^"]*">([^<]*)</h4>')
_HASH = re.compile(r'data-hash="([0-9a-f]+)"')
_SENTINEL = "\x00container\x00"


def _fill_root(
    body: str, root: str, kind: str, taken: set[str]
) -> tuple[str, str, str, list[str]]:
    """(body, filled HTML, copy text, held hashes) with the held blocks moved in."""
    pieces = _SLOT.split(root)  # text, id, text, id, ..., text
    out: list[str] = []
    copies: list[str] = []
    hashes: list[str] = []
    for text, held in zip(pieces[0::2], [*pieces[1::2], None], strict=False):
        out.append(text)
        label = _LABEL.findall(text)
        copies += [html.unescape(label[-1])] if label else []
        if held is None:
            continue
        body, block, copy = _take(body, held, kind, taken)
        out.append(f'<div class="vd-containers-slot">{block}</div>')
        copies += [copy] if copy else []
        hashes += _HASH.findall(block[:300])
    return body, "".join(out), "\n\n".join(copies), hashes


def _stamp(filled: str, copy: str, hashes: list[str]) -> str:
    """Give the container the copy text and a hash that changes with its held blocks."""
    filled = filled.replace(' data-copy=""', copy_attr(copy), 1)
    own = _HASH.search(filled)
    if own is None or not hashes:
        return filled
    digest = hashlib.sha256((own.group(1) + "".join(hashes)).encode()).hexdigest()[:12]
    return filled.replace(own.group(0), f'data-hash="{digest}"', 1)


def _fill_one(body: str, ident: str, kind: str, taken: set[str]) -> str:
    start = _block_start(body, ident)
    end = _block_end(body, start)
    root = body[start:end]
    body = body[:start] + _SENTINEL + body[end:]
    body, filled, copy, hashes = _fill_root(body, root, kind, taken)
    return body.replace(_SENTINEL, _stamp(filled, copy, hashes), 1)


def fill_containers(body: str) -> str:
    """Move each container's held blocks into its panels (hash and copy included)."""
    taken: set[str] = set()
    for found in list(_ROOT.finditer(body)):
        body = _fill_one(body, found.group(1), found.group(3), taken)
    return body
