"""HTML for the stats block: a grid of cards (label, value, optional change).

Server-rendered; no script. The change shows an arrow, the word up, down or flat and
the number as text. Its tone reaches the page only as a `vd-stats-<tone>` class, so
every colour comes from the `--vd-tone-*` tokens.
"""

from varde_learn.docs.pages.blocks.stats import SIGNS, delta_direction
from varde_learn.docs.pages.blocks_render.callout import inline
from varde_learn.docs.pages.blocks_render.common import as_list, esc
from varde_learn.docs.pages.blocks_render.svg import copy_attr

ARROWS = {"up": "▲", "down": "▼", "flat": "▬"}
GOOD_TONE = {True: "success", False: "risk"}


def format_number(value: float, decimals: object) -> str:
    """Group thousands with commas; `decimals` fixes the places."""
    if isinstance(decimals, int):
        return f"{value:,.{decimals}f}"
    return f"{value:,}"


def value_text(item: dict[str, object]) -> str:
    value = item["value"]
    if isinstance(value, str):
        return value
    return format_number(value, item.get("decimals"))  # type: ignore[arg-type]


def delta_text(item: dict[str, object]) -> str:
    """The delta as text without its sign: the direction word carries the sign."""
    delta = item["delta"]
    if isinstance(delta, str):
        return delta.strip().lstrip("".join(SIGNS)).strip()
    return format_number(abs(delta), item.get("decimals"))  # type: ignore[arg-type]


def item_tone(item: dict[str, object], direction: str | None) -> str:
    tone = item.get("tone")
    if isinstance(tone, str):
        return tone
    good = item.get("good")
    if good is None or direction in (None, "flat"):
        return "neutral"
    return GOOD_TONE[direction == good]


def spoken_delta(item: dict[str, object]) -> str:
    """`up 12%`, or `flat` alone when the delta is empty."""
    direction = delta_direction(item) or "flat"
    return f"{direction} {delta_text(item)}".strip()


def card_name(item: dict[str, object]) -> str:
    delta = f", {spoken_delta(item)}" if "delta" in item else ""
    return f"{item['label']}: {value_text(item)}{delta}"


def copy_text(items: list[dict[str, object]]) -> str:
    def line(item: dict[str, object]) -> str:
        delta = f" ({spoken_delta(item)})" if "delta" in item else ""
        return f"{item['label']}: {value_text(item)}{delta}"

    return "\n".join(line(i) for i in items)


def _delta(item: dict[str, object]) -> str:
    if "delta" not in item:
        return ""
    direction = delta_direction(item) or "flat"
    number = esc(delta_text(item))
    return (
        '<dd class="vd-stats-delta">'
        '<span class="vd-stats-mark">'
        f'<span class="vd-stats-glyph" aria-hidden="true">{ARROWS[direction]}</span> '
        f'<span class="vd-stats-word">{direction}</span></span>'
        f' <span class="vd-stats-number">{number}</span></dd>'
    )


def _card(item: dict[str, object]) -> str:
    tone = item_tone(item, delta_direction(item))
    note = (
        f'<dd class="vd-stats-note">{inline(str(item["note"]))}</dd>'
        if "note" in item
        else ""
    )
    return (
        f'<div class="vd-stats-card vd-stats-{tone}" role="group" '
        f'aria-label="{esc(card_name(item))}"><dl class="vd-stats-body">'
        f'<dt class="vd-stats-label">{esc(item["label"])}</dt>'
        f'<dd class="vd-stats-value">{esc(value_text(item))}</dd>'
        f"{_delta(item)}{note}</dl></div>"
    )


def render_stats(data: dict[str, object]) -> str:
    items = [i for i in as_list(data["item"]) if isinstance(i, dict)]
    count = len(items)
    noun = "stat" if count == 1 else "stats"
    return (
        '<section class="vb stats vd-stats" aria-label="Stats"'
        f"{copy_attr(copy_text(items))}>"
        f'<p class="vb-alt vd-stats-summary">{count} {noun}</p>'
        f'<div class="vd-stats-grid vd-stats-n{count}">'
        f"{''.join(_card(i) for i in items)}</div></section>"
    )
