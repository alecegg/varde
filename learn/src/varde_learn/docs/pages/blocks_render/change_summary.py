"""HTML for the change-summary block: an info-toned panel holding one sentence.

Server-rendered; no script. The sentence is the text alternative and the copy text.
Every colour comes from the `--vd-tone-info-*` tokens.
"""

from collections.abc import Iterable

from varde_learn.docs.pages.blocks.change_summary import UNCOUNTED, Marker, sentence
from varde_learn.docs.pages.blocks_render.common import esc
from varde_learn.docs.pages.blocks_render.svg import copy_attr


def render_change_summary(
    data: dict[str, object], markers: Iterable[Marker] | None = None
) -> str:
    # No marker list means the page was not scanned: do not claim there are none.
    text = UNCOUNTED if markers is None else sentence(markers)
    title = str(data["title"]) if "title" in data else ""
    heading = f'<p class="vd-change-summary-title">{esc(title)}</p>' if title else ""
    copy = "\n".join(part for part in (title, text) if part)
    return (
        '<aside class="vb change-summary vd-change-summary"'
        ' aria-label="Change summary"'
        f"{copy_attr(copy)}>"
        '<p class="vd-change-summary-label">'
        '<span class="vd-change-summary-glyph" aria-hidden="true">~</span> Changes</p>'
        f"{heading}"
        f'<p class="vb-alt vd-change-summary-text">{esc(text)}</p></aside>'
    )
