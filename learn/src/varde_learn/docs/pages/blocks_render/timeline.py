"""HTML for the timeline block: an ordered list with a CSS rail and one node per item.

Server-rendered; no script. Status is a glyph, a word and a tone class, never colour
alone. The first active item carries `aria-current="step"`. A horizontal timeline sits
in a focusable scroll region; the stylesheet stacks it below 44rem.
"""

from varde_learn.docs.pages.blocks_render.callout import inline
from varde_learn.docs.pages.blocks_render.common import as_list, esc
from varde_learn.docs.pages.blocks_render.svg import copy_attr

GLYPHS = {"done": "✓", "active": "●", "planned": "○", "blocked": "✕"}
WORDS = {"done": "Done", "active": "Active", "planned": "Planned", "blocked": "Blocked"}


def copy_text(items: list[dict[str, object]]) -> str:
    return "\n".join(f"{i['when']}: {i['label']} ({i['status']})" for i in items)


def summary_text(items: list[dict[str, object]]) -> str:
    """`4 milestones: 2 done, 1 active, 1 planned`; counts of zero are left out."""
    count = len(items)
    parts = [
        f"{n} {status}"
        for status in GLYPHS
        if (n := sum(1 for i in items if i["status"] == status))
    ]
    noun = "milestone" if count == 1 else "milestones"
    return f"{count} {noun}: {', '.join(parts)}"


def current_index(items: list[dict[str, object]]) -> int | None:
    """The first active item, the only one marked as the current step."""
    return next((n for n, i in enumerate(items) if i["status"] == "active"), None)


def _extras(item: dict[str, object]) -> str:
    note = (
        f'<p class="vd-timeline-note">{inline(str(item["note"]))}</p>'
        if "note" in item
        else ""
    )
    owner = (
        f'<p class="vd-timeline-owner">Owner: {esc(item["owner"])}</p>'
        if "owner" in item
        else ""
    )
    return note + owner


def _item(item: dict[str, object], current: bool) -> str:
    status = str(item["status"])
    mark = ' aria-current="step"' if current else ""
    return (
        f'<li class="vd-timeline-item vd-timeline-{status}"{mark}>'
        f'<span class="vd-timeline-node" aria-hidden="true">{GLYPHS[status]}</span>'
        '<div class="vd-timeline-body">'
        f'<p class="vd-timeline-when">{esc(item["when"])}</p>'
        f'<p class="vd-timeline-label">{esc(item["label"])}</p>'
        f'<p class="vd-timeline-status">{WORDS[status]}</p>'
        f"{_extras(item)}</div></li>"
    )


def _scroll(title: str, inner: str) -> str:
    return (
        '<div class="vd-timeline-scroll" role="region" '
        f'aria-label="{esc(title)}, scrollable" tabindex="0">{inner}</div>'
    )


def render_timeline(data: dict[str, object]) -> str:
    items = [i for i in as_list(data["item"]) if isinstance(i, dict)]
    horizontal = data.get("orientation") == "horizontal"
    title = str(data.get("title") or "Timeline")
    current = current_index(items)
    rows = "".join(_item(i, n == current) for n, i in enumerate(items))
    lst = (
        f'<ol class="vd-timeline-list" role="list" aria-label="{esc(title)}">'
        f"{rows}</ol>"
    )
    layout = "horizontal" if horizontal else "vertical"
    caption = (
        f'<p class="vd-timeline-title">{esc(data["title"])}</p>'
        if data.get("title")
        else ""
    )
    return (
        f'<section class="vb timeline vd-timeline vd-timeline-{layout}" '
        f'aria-label="{esc(title)}"{copy_attr(copy_text(items))}>'
        f"{caption}"
        f'<p class="vb-alt vd-timeline-summary">{esc(summary_text(items))}</p>'
        f"{_scroll(title, lst) if horizontal else lst}</section>"
    )
