"""HTML for the callout block: a toned note with a glyph, the tone word and plain text.

Server-rendered; no script. The tone reaches the page only as a `vd-callout-<tone>`
class, so every colour comes from the `--vd-tone-*` tokens.
"""

import re

from varde_learn.docs.pages.blocks_render.common import esc
from varde_learn.docs.pages.blocks_render.svg import copy_attr

TONE_LABELS = {
    "info": ("i", "Info"),
    "decision": ("◆", "Decision"),
    "risk": ("▲", "Risk"),
    "warning": ("!", "Warning"),
    "success": ("✓", "Success"),
}
_CODE = re.compile(r"`([^`\n]+)`")


def inline(text: str) -> str:
    """Escape plain text, then turn each backtick span into `<code>`."""
    return _CODE.sub(r"<code>\1</code>", esc(text))


def copy_text(data: dict[str, object]) -> str:
    title = str(data["title"]) if "title" in data else ""
    return "\n".join(part for part in (title, str(data["text"])) if part)


def render_callout(data: dict[str, object]) -> str:
    tone = str(data["tone"])
    glyph, word = TONE_LABELS[tone]
    title = (
        f'<p class="vd-callout-title">{esc(data["title"])}</p>'
        if "title" in data
        else ""
    )
    paragraphs = (p for p in re.split(r"\n\s*\n", str(data["text"])) if p.strip())
    body = "".join(
        f'<p class="vd-callout-text">{inline(p.strip())}</p>' for p in paragraphs
    )
    label = (
        '<p class="vd-callout-label">'
        f'<span class="vd-callout-glyph" aria-hidden="true">{glyph}</span> {word}</p>'
    )
    return (
        f'<aside class="vb callout vd-callout vd-callout-{tone}"'
        f"{copy_attr(copy_text(data))}>"
        f"{label}{title}{body}</aside>"
    )
