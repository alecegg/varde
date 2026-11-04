"""HTML for the checklist block: state glyph and word per item, progress bar and count.

Server-rendered; no script and no checkbox input, so nothing is interactive. The state
reaches the page only as a `vd-checklist-<state>` class, so colours come from tokens.
"""

from varde_learn.docs.pages.blocks_render.callout import inline
from varde_learn.docs.pages.blocks_render.common import as_list, esc
from varde_learn.docs.pages.blocks_render.svg import copy_attr

STATES = {"done": ("✓", "Done"), "open": ("○", "Open"), "blocked": ("✕", "Blocked")}


def item_state(item: dict[str, object]) -> str:
    status = item.get("status")
    if isinstance(status, str):
        return status
    return "done" if item.get("checked") is True else "open"


def count_text(done: int, total: int) -> str:
    return f"{done} of {total} done"


def _mark(item: dict[str, object]) -> str:
    return "x" if item_state(item) == "done" else " "


def copy_text(data: dict[str, object], items: list[dict[str, object]]) -> str:
    title = str(data["title"]) if "title" in data else ""
    lines = [f"- [{_mark(i)}] {i['label']}" for i in items]
    return "\n".join(part for part in (title, *lines) if part)


def _item(item: dict[str, object]) -> str:
    state = item_state(item)
    glyph, word = STATES[state]
    note = (
        f'<span class="vd-checklist-note">{inline(str(item["note"]))}</span>'
        if "note" in item
        else ""
    )
    return (
        f'<li class="vd-checklist-item vd-checklist-{state}">'
        f'<span class="vd-checklist-state"><span class="vd-checklist-glyph" '
        f'aria-hidden="true">{glyph}</span> {word}</span>'
        f'<span class="vd-checklist-text">'
        f'<span class="vd-checklist-label">{inline(str(item["label"]))}</span>'
        f"{note}</span></li>"
    )


def render_checklist(data: dict[str, object]) -> str:
    items = [i for i in as_list(data["items"]) if isinstance(i, dict)]
    done = sum(1 for i in items if item_state(i) == "done")
    count = count_text(done, len(items))
    title = (
        f'<p class="vd-checklist-title">{esc(data["title"])}</p>'
        if "title" in data
        else ""
    )
    body = (
        f'<ul class="vd-checklist-list" aria-label="Checklist, {count}">'
        f"{''.join(_item(i) for i in items)}</ul>"
        if items
        else '<p class="vd-checklist-empty">No items.</p>'
    )
    progress = (
        '<div class="vd-checklist-progress">'
        f'<progress class="vd-checklist-bar" value="{done}" '
        f'max="{max(len(items), 1)}" aria-label="Progress">{count}</progress>'
        f'<p class="vb-alt vd-checklist-count">{count}</p></div>'
    )
    return (
        f'<section class="vb checklist vd-checklist" aria-label="Checklist"'
        f"{copy_attr(copy_text(data, items))}>{title}{progress}{body}</section>"
    )
