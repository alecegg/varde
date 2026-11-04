"""Chart event markers and bands: SVG, the Events list and the table rows. Pure.

Bands are tinted rects with a per-tone hatch (so tones differ without colour);
markers are dashed lines with a circle pin, bands get a square pin. Every pin
carries the event number; the Events list repeats each event as text, and
`static/chart.js` turns its items into buttons that show the tooltip.
"""

from dataclasses import dataclass

from varde_learn.docs.pages.blocks_render.chart_model import (
    Event,
    Model,
    event_rows,
    where,
)
from varde_learn.docs.pages.blocks_render.chart_scale import CHAR, ellipsize
from varde_learn.docs.pages.blocks_render.common import count_noun, data_scroll, esc

ROW = 28.0
PIN = 22.0  # pin width; its height is 20 (square) or 22 (circle)
HATCH = {"info": "/", "decision": "\\", "risk": "x", "warning": "-", "success": "|"}
MAX_ROWS = 3
LABEL_CHARS = 14


@dataclass(frozen=True)
class Pin:
    event: Event
    x: float  # centre
    lane: int
    label: str  # shortened text drawn beside the pin; empty when it would overlap


def rows_for(count: int) -> int:
    return 0 if count == 0 else min(MAX_ROWS, 1 + (count - 1) // 4)


def events_top(model: Model) -> float | None:
    """Where the plot starts when there are events, else None."""
    rows = rows_for(len(model.events))
    return 10.0 + ROW * rows if rows else None


def hatch_path(x0: float, y0: float, x1: float, y1: float, style: str) -> str:
    """Hatch lines clipped to a rect: '/' '\\' 'x' (both), '-' or '|'. Gap is 8."""
    gap = 8.0
    w, h = x1 - x0, y1 - y0
    d: list[str] = []
    if style in "/x":
        c = -h
        while c < w:
            ta, tb = max(0.0, -c), min(h, w - c)
            if ta < tb:
                d.append(
                    f"M{x0 + c + ta:.1f} {y1 - ta:.1f}L{x0 + c + tb:.1f} {y1 - tb:.1f}"
                )
            c += gap
    if style in "\\x":
        c = -h
        while c < w:
            ta, tb = max(0.0, -c), min(h, w - c)
            if ta < tb:
                d.append(
                    f"M{x0 + c + ta:.1f} {y0 + ta:.1f}L{x0 + c + tb:.1f} {y0 + tb:.1f}"
                )
            c += gap
    if style == "-":
        d += [
            f"M{x0:.1f} {y:.1f}L{x1:.1f} {y:.1f}" for y in _steps(y0 + gap / 2, y1, gap)
        ]
    if style == "|":
        d += [
            f"M{x:.1f} {y0:.1f}L{x:.1f} {y1:.1f}" for x in _steps(x0 + gap / 2, x1, gap)
        ]
    return "".join(d)


def _steps(start: float, stop: float, step: float) -> list[float]:
    count = max(int((stop - start) / step) + 1, 0)
    return [start + step * i for i in range(count) if start + step * i < stop]


def place_pins(
    spans: list[tuple[Event, float, float]], left: float, right: float, rows: int
) -> list[Pin]:
    """Pins on up to three rows; a label that would overlap is dropped, a pin never."""
    half = PIN / 2
    ends = [left - 8.0] * max(rows, 1)
    pins: list[Pin] = []
    for event, x0, _ in spans:
        anchor = x0 if event.end is None else x0 + half
        x = min(max(anchor, left + half), right - half)
        text = ellipsize(event.label, LABEL_CHARS)
        reach = 4 + len(text) * CHAR
        pin = _fit(ends, event, x, text, reach, right)
        pins.append(pin)
    return pins


def _fit(
    ends: list[float], event: Event, x: float, text: str, reach: float, right: float
) -> Pin:
    half = PIN / 2
    for with_label in (True, False):
        extent = reach if with_label else 0.0
        for row, end in enumerate(ends):
            if x - half >= end + 4 and x + half + extent <= right:
                ends[row] = x + half + extent
                return Pin(event, x, row, text if with_label else "")
    row = min(range(len(ends)), key=ends.__getitem__)
    x = min(max(x, ends[row] + 4 + half), right - half)
    ends[row] = max(ends[row], x + half)
    return Pin(event, x, row, "")


def _classes(event: Event, extra: str) -> str:
    return f"vb-ev vb-ev-t-{event.tone} {extra}"


def _band(event: Event, x0: float, x1: float, top: float, bottom: float) -> str:
    x1 = max(x1, x0 + 1.0)
    rect = (
        f'<rect class="vb-band" x="{x0:.1f}" y="{top:.1f}" '
        f'width="{x1 - x0:.1f}" height="{bottom - top:.1f}"/>'
    )
    path = hatch_path(x0, top, x1, bottom, HATCH[event.tone])
    hatch = f'<path class="vb-hatch" d="{path}"/>'
    rule = (
        f'<line class="vb-band-rule" x1="{x0:.1f}" y1="{top:.1f}" '
        f'x2="{x1:.1f}" y2="{top:.1f}"/>'
    )
    return (
        f'<g class="{_classes(event, "vb-ev-band")}" data-event="{event.n}">'
        f"{rect}{hatch}{rule}</g>"
    )


def _rule(event: Event, x: float, from_y: float, bottom: float) -> str:
    return (
        f'<g class="{_classes(event, "vb-ev-marker")}" data-event="{event.n}">'
        f'<line class="vb-ev-line" x1="{x:.1f}" y1="{from_y:.1f}" '
        f'x2="{x:.1f}" y2="{bottom:.1f}"/></g>'
    )


def _pin(pin: Pin) -> str:
    event, x = pin.event, pin.x
    cy = 15.0 + ROW * pin.lane
    half = PIN / 2
    if event.end is None:
        shape = f'<circle class="vb-ev-shape" cx="{x:.1f}" cy="{cy:.1f}" r="{half:g}"/>'
        shape += (
            f'<polygon class="vb-ev-glyph" points="{x - 5:.1f},{cy + half:.1f} '
            f'{x + 5:.1f},{cy + half:.1f} {x:.1f},{cy + half + 6:.1f}"/>'
        )
    else:
        shape = (
            f'<rect class="vb-ev-shape" x="{x - half:.1f}" y="{cy - 10:.1f}" '
            f'width="{PIN:g}" height="20" rx="4"/>'
        )
    number = (
        f'<text class="vb-ev-no" x="{x:.1f}" y="{cy + 5:.1f}" '
        f'text-anchor="middle">{event.n}</text>'
    )
    label = ""
    if pin.label:
        label = (
            f'<text class="vb-note-label vb-ev-text" x="{x + half + 4:.1f}" '
            f'y="{cy + 5:.1f}" text-anchor="start">{esc(pin.label)}</text>'
        )
    kind = "vb-ev-marker" if event.end is None else "vb-ev-band"
    return (
        f'<g class="{_classes(event, kind + " vb-ev-pin")}" data-event="{event.n}">'
        f"{shape}{number}{label}</g>"
    )


def draw_events(
    model: Model,
    spans: list[tuple[Event, float, float]],
    left: float,
    right: float,
    top: float,
    bottom: float,
) -> str:
    """Bands first (behind the data), then marker lines, then the pins."""
    bands = [_band(e, x0, x1, top, bottom) for e, x0, x1 in spans if e.end is not None]
    pins = place_pins(spans, left, right, rows_for(len(model.events)))
    lines = [_rule(e, x0, top - 4, bottom) for e, x0, _ in spans if e.end is None]
    return "".join(bands + lines + [_pin(p) for p in pins])


def events_sentence(count: int) -> str:
    verb = "is" if count == 1 else "are"
    return f"{count_noun(count, 'event', 'events')} {verb} listed under the chart."


def events_list(model: Model) -> str:
    """The text alternative for the pins; the script makes each item a button."""
    items = "".join(
        f'<li class="{_classes(e, "vb-ev-" + e.kind)}" data-event="{e.n}" '
        f'data-kind="{e.kind}" data-where="{esc(where(model, e))}" '
        f'data-tone="{e.tone}">'
        f'<span class="vb-ev-num">{e.n}</span>'
        f'<span class="vb-ev-label">{esc(e.label)}</span> '
        f'<span class="vb-ev-meta">({e.kind}, {esc(where(model, e))}, '
        f"{e.tone})</span></li>"
        for e in model.events
    )
    return f'<h5 class="vb-events-title">Events</h5><ol class="vb-events">{items}</ol>'


def events_table(model: Model) -> str:
    head = "".join(f"<th>{c}</th>" for c in ("Event", "Kind", "Where", "Tone"))
    rows = "".join(
        f'<tr><th scope="row">{esc(label)}</th>'
        + "".join(f"<td>{esc(c)}</td>" for c in rest)
        + "</tr>"
        for label, *rest in event_rows(model)
    )
    grid = (
        f'<table class="vb-data-grid"><thead><tr>{head}</tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )
    return f"<h5>Events</h5>{data_scroll(grid, 'Events table')}"
