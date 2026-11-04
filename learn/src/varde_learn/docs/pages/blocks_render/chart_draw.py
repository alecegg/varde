"""SVG for each chart kind: pure functions from a Model to markup.

Everything is class- and attribute-styled (no `style=`); colours come from the
`--vd-series-*` tokens in `41-chart.css`. Text is 15 viewBox units, so it stays
at or above 11 CSS px while the SVG is at least 264 px wide; labels thin out
instead of overlapping. Marks carry `data-series` and `data-index` for the
script, plus an `aria-label` reading.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

from varde_learn.docs.pages.blocks_render.chart_events import draw_events, events_top
from varde_learn.docs.pages.blocks_render.chart_model import (
    Model,
    Series,
    colour,
    dash_of,
    marker_of,
    reading,
    show,
)
from varde_learn.docs.pages.blocks_render.chart_scale import (
    CHAR,
    compact,
    ellipsize,
    nice_ticks,
    thin_step,
    tick_decimals,
)
from varde_learn.docs.pages.blocks_render.common import esc

W, H = 360.0, 220.0
SPARK_W, SPARK_H = 160.0, 44.0
BOTTOM, NOTE_ROW = 34.0, 17.0
DENSE_POINTS = 24
MAX_END_SERIES = 6


@dataclass(frozen=True)
class Drawing:
    inner: str
    width: float
    height: float
    dense: bool


@dataclass(frozen=True)
class Axis:
    ticks: list[float]
    start: float  # pixel position of the first tick
    end: float  # pixel position of the last tick
    decimals: int

    def at(self, value: float) -> float:
        span = self.ticks[-1] - self.ticks[0]
        return self.start + (value - self.ticks[0]) / span * (self.end - self.start)

    def text(self, value: float) -> str:
        return compact(value, self.decimals)

    def width(self) -> float:
        return max(len(self.text(t)) for t in self.ticks) * CHAR


@dataclass(frozen=True)
class Frame:
    x0: float
    x1: float
    y0: float
    y1: float


def make_axis(
    low: float, high: float, start: float, end: float, zero: bool, decimals: int | None
) -> Axis:
    if zero:
        low, high = min(low, 0.0), max(high, 0.0)
    if low == high == 0:
        high = 1.0
    ticks = nice_ticks(low, high)
    return Axis(
        ticks, start, end, tick_decimals(ticks) if decimals is None else decimals
    )


def _text(cls: str, x: float, y: float, anchor: str, text: str, extra: str = "") -> str:
    pos = f'x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}"'
    return f'<text class="{cls}" {pos}{extra}>{esc(text)}</text>'


def _line(cls: str, x1: float, y1: float, x2: float, y2: float) -> str:
    pos = f'x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"'
    return f'<line class="{cls}" {pos}/>'


def _attrs(model: Model, s: Series, i: int) -> str:
    return (
        f'data-series="{s.n}" data-index="{i}" data-marker="{marker_of(s.n)}" '
        f'data-dash="{dash_of(s.n)}" aria-label="{esc(reading(model, s, i))}"'
    )


def symbol(
    shape: str, cx: float, cy: float, r: float, cls: str, attrs: str = ""
) -> str:
    """One point marker; cross and plus are open strokes, the rest are filled."""
    x, y = f"{cx:.1f}", f"{cy:.1f}"

    def tag(name: str, geometry: str, extra: str = "") -> str:
        c = f"{cls} vb-sym{extra}"
        return f'<{name} class="{c}" {attrs} {geometry}/>'.replace("  ", " ")

    if shape == "circle":
        return tag("circle", f'cx="{x}" cy="{y}" r="{r:g}"')
    if shape == "square":
        side = r * 1.8
        box = (
            f'x="{cx - side / 2:.1f}" y="{cy - side / 2:.1f}" '
            f'width="{side:.1f}" height="{side:.1f}"'
        )
        return tag("rect", box)
    if shape == "triangle":
        pts = [
            (cx, cy - r * 1.2),
            (cx + r * 1.1, cy + r * 0.9),
            (cx - r * 1.1, cy + r * 0.9),
        ]
    elif shape == "diamond":
        pts = [
            (cx, cy - r * 1.3),
            (cx + r * 1.3, cy),
            (cx, cy + r * 1.3),
            (cx - r * 1.3, cy),
        ]
    elif shape == "cross":
        d = (
            f"M{cx - r:.1f} {cy - r:.1f}L{cx + r:.1f} {cy + r:.1f}"
            f"M{cx + r:.1f} {cy - r:.1f}L{cx - r:.1f} {cy + r:.1f}"
        )
        return tag("path", f'd="{d}"', " vb-open")
    else:
        d = (
            f"M{cx - r:.1f} {cy:.1f}L{cx + r:.1f} {cy:.1f}"
            f"M{cx:.1f} {cy - r:.1f}L{cx:.1f} {cy + r:.1f}"
        )
        return tag("path", f'd="{d}"', " vb-open")
    return tag(
        "polygon", 'points="' + " ".join(f"{px:.1f},{py:.1f}" for px, py in pts) + '"'
    )


def _dot(model: Model, s: Series, i: int, x: float, y: float, last: bool) -> str:
    cls = f"vb-dot vb-mark vb-s{colour(s.n)}" + (" vb-last" if last else "")
    return symbol(marker_of(s.n), x, y, 4.5, cls, _attrs(model, s, i))


def _outline(s: Series) -> str:
    """A dashed bar outline: invisible on screen, tells series apart in print."""
    dash = dash_of(s.n)
    return f' stroke-dasharray="{dash}"' if dash else ""


def _poly(kind: str, s: Series, points: list[tuple[float, float]], name: str) -> str:
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    dash = dash_of(s.n)
    dashed = f' stroke-dasharray="{dash}"' if dash and kind == "line" else ""
    tag = "polyline" if kind == "line" else "polygon"
    cls = f"vb-{kind} vb-s{colour(s.n)}"
    return (
        f'<{tag} class="{cls}" data-series="{s.n}" data-marker="{marker_of(s.n)}" '
        f'data-dash="{dash}" aria-label="{esc(name)}" points="{pts}"{dashed}/>'
    )


def _spans(model: Model) -> dict[int, list[tuple[float, float]]]:
    """Each point's (base, top): zero to the value, or stacked for stacked bars."""
    count = len(model.labels)
    pos, neg = [0.0] * count, [0.0] * count
    spans: dict[int, list[tuple[float, float]]] = {}
    for s in model.series:
        if s.kind != "bar" or not model.stack:
            spans[s.n] = [(0.0, v) for v in s.values]
            continue
        pairs = []
        for i, v in enumerate(s.values):
            run = pos if v >= 0 else neg
            pairs.append((run[i], run[i] + v))
            run[i] += v
        spans[s.n] = pairs
    return spans


def _extent(
    group: list[Series], spans: dict[int, list[tuple[float, float]]]
) -> tuple[float, float]:
    values: list[float] = []
    for s in group:
        if s.kind in ("bar", "area"):
            values += [v for pair in spans[s.n] for v in pair]
        else:
            values += s.values
    return min(values), max(values)


def _note_texts(notes: list[tuple[str, float]], frame: Frame, top: float) -> str:
    """Note labels on two rows; one that would overlap on both is left to the list."""
    ends = [frame.x0 - 1, frame.x0 - 1]
    out = []
    for text, x in notes:
        label = ellipsize(text, 22)
        width = len(label) * CHAR
        anchor = "start" if x - frame.x0 < width / 2 + 4 else "middle"
        left = x if anchor == "start" else x - width / 2
        for row in (0, 1):
            if left > ends[row] + 6:
                ends[row] = left + width
                y = top - 6 - row * NOTE_ROW
                out.append(_text("vb-note-label", x, y, anchor, label))
                break
    return "".join(out)


def _end_labels(model: Model, frame: Frame, ys: dict[int, float], room: float) -> str:
    """Direct labels at the right end of each line; none if they cannot all fit."""
    order = sorted(ys.items(), key=lambda kv: kv[1])
    placed: list[tuple[int, float]] = []
    for n, y in order:
        floor = placed[-1][1] + 17 if placed else y
        placed.append((n, max(y, floor)))
    if placed and placed[-1][1] > frame.y1 + 6:
        return ""
    names = {s.n: s.name for s in model.series}
    limit = int((room - 6) / CHAR)
    return "".join(
        _text(
            "vb-end",
            frame.x1 + 8,
            y + 5,
            "start",
            ellipsize(names[n], limit),
            f' data-series="{n}"',
        )
        for n, y in placed
    )


def _note_xs(model: Model, count: int) -> list[tuple[str, int]]:
    known = [
        (text, model.labels.index(str(x)))
        for x, text in model.notes
        if str(x) in model.labels
    ]
    return known if count else []


def categorical(model: Model) -> Drawing:
    """Bar, line, area and combined charts over text labels, on one or two axes."""
    count = len(model.labels)
    notes_at = _note_xs(model, count)
    top = events_top(model) or 12.0 + NOTE_ROW * min(2, len(notes_at))
    spans = _spans(model)
    axes: dict[str, Axis] = {}
    for side in ("left", "right"):
        group = [s for s in model.series if s.axis == side]
        if not group:
            continue
        low, high = _extent(group, spans)
        zero = any(s.kind in ("bar", "area") for s in group)
        axes[side] = make_axis(low, high, H - BOTTOM, top, zero, model.decimals)
    left = axes["left"].width() + 12 if "left" in axes else 12.0
    right = axes["right"].width() + 12 if "right" in axes else 12.0
    room = min(max(len(s.name) for s in model.series), 12) * CHAR + 14
    want_ends = (
        model.kind in ("line", "area")
        and 1 < len(model.series) <= MAX_END_SERIES
        and "right" not in axes
        and W - left - 16 - room >= 150
    )
    if want_ends:
        right = room + 4
    frame = Frame(left, W - right, top, H - BOTTOM)
    slot = (frame.x1 - frame.x0) / max(count, 1)

    def cx(i: int) -> float:
        return frame.x0 + slot * (i + 0.5)

    bars = [s for s in model.series if s.kind == "bar"]
    group = 1 if model.stack else max(len(bars), 1)
    width = max(slot * 0.8 / group, 0.6)
    under: list[str] = []
    over: list[str] = []
    dots: list[str] = []
    ends: dict[int, float] = {}
    for s in model.series:
        axis = axes[s.axis]
        if s.kind == "bar":
            k = 0 if model.stack else bars.index(s)
            shift = width * k - width * group / 2
            under += _bars(
                model, s, spans[s.n], axis, lambda i, d=shift: cx(i) + d, width
            )
            continue
        points = [(cx(i), axis.at(v)) for i, v in enumerate(s.values)]
        if s.kind == "area":
            base = axis.at(max(axis.ticks[0], min(0.0, axis.ticks[-1])))
            shape = [(points[0][0], base), *points, (points[-1][0], base)]
            under.append(_poly("area", s, shape, s.name))
        over.append(_poly("line", s, points, s.name))
        dots += [
            _dot(model, s, i, x, y, i == count - 1) for i, (x, y) in enumerate(points)
        ]
        ends[s.n] = points[-1][1]
    parts = [
        _grid(frame, axes),
        _category_events(model, frame, slot, top)
        or _notes([(text, cx(i)) for text, i in notes_at], frame, top),
        _category_labels(model, frame, slot),
        _columns(frame, count, slot),
        *under,
        *over,
        *dots,
    ]
    if want_ends:
        parts.append(_end_labels(model, frame, ends, room))
    return Drawing("".join(parts), W, H, count > DENSE_POINTS)


def _category_events(model: Model, frame: Frame, slot: float, top: float) -> str:
    """Bands and markers over text labels; empty when the chart has no events."""
    spans = []
    for event in model.events:
        first = model.labels.index(str(event.start))
        last = first if event.end is None else model.labels.index(str(event.end))
        x0 = frame.x0 + slot * (first + (0.5 if event.end is None else 0.0))
        x1 = frame.x0 + slot * (last + (0.5 if event.end is None else 1.0))
        spans.append((event, x0, x1))
    return draw_events(model, spans, frame.x0, frame.x1, top, frame.y1) if spans else ""


def _grid(frame: Frame, axes: dict[str, Axis]) -> str:
    out = []
    for side, axis in axes.items():
        for t in axis.ticks:
            y = axis.at(t)
            if axis is next(iter(axes.values())):
                out.append(
                    _line("vb-axis" if t == 0 else "vb-grid", frame.x0, y, frame.x1, y)
                )
            anchor, x = (
                ("end", frame.x0 - 6) if side == "left" else ("start", frame.x1 + 6)
            )
            out.append(_text("vb-tick", x, y + 5, anchor, axis.text(t)))
    out.append(_line("vb-axis", frame.x0, frame.y1, frame.x1, frame.y1))
    return "".join(out)


def _category_labels(model: Model, frame: Frame, slot: float) -> str:
    shown = [ellipsize(label, 12) for label in model.labels]
    widest = max(len(label) for label in shown) * CHAR
    step = thin_step(len(shown), slot, widest)
    return "".join(
        _text("vb-tick", frame.x0 + slot * (i + 0.5), frame.y1 + 22, "middle", label)
        for i, label in enumerate(shown)
        if i % step == 0
    )


def _columns(frame: Frame, count: int, slot: float) -> str:
    return "".join(
        f'<rect class="vb-col" data-index="{i}" x="{frame.x0 + slot * i:.1f}" '
        f'y="{frame.y0:.1f}" width="{slot:.1f}" height="{frame.y1 - frame.y0:.1f}"/>'
        for i in range(count)
    )


def _bars(
    model: Model,
    s: Series,
    spans: list[tuple[float, float]],
    axis: Axis,
    x_of: Callable[[int], float],
    width: float,
) -> list[str]:
    out = []
    for i, (base, top) in enumerate(spans):
        a, b = axis.at(base), axis.at(top)
        height = max(abs(a - b), 1.0)
        y = min(a, b) if abs(a - b) >= 1.0 else a - 0.5
        x = x_of(i)
        out.append(
            f'<rect class="vb-bar vb-mark vb-s{colour(s.n)}" '
            f"{_attrs(model, s, i)}{_outline(s)} "
            f'x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}"/>'
        )
    return out


def _notes(marked: list[tuple[str, float]], frame: Frame, top: float) -> str:
    rules = "".join(
        f'<line class="vb-note" x1="{x:.1f}" y1="{top - 4:.1f}" '
        f'x2="{x:.1f}" y2="{frame.y1:.1f}"/>'
        for _, x in marked
    )
    return rules + _note_texts(marked, frame, top)


def horizontal_bars(model: Model) -> Drawing:
    """Bars growing rightwards from a zero line, one row per label."""
    count, group = len(model.labels), 1 if model.stack else len(model.series)
    row = max(24.0, group * 14.0)
    height = min(40.0 + count * row, 1400.0)
    spans = _spans(model)
    low, high = _extent(model.series, spans)
    shown = [ellipsize(label, 14) for label in model.labels]
    left = max(len(label) for label in shown) * CHAR + 12
    frame = Frame(left, W - 14, 8.0, height - BOTTOM)
    axis = make_axis(low, high, frame.x0, frame.x1, True, model.decimals)
    slot = (frame.y1 - frame.y0) / max(count, 1)
    out = []
    for t in axis.ticks:
        x = axis.at(t)
        out.append(_line("vb-axis" if t == 0 else "vb-grid", x, frame.y0, x, frame.y1))
        out.append(_text("vb-tick", x, frame.y1 + 22, "middle", axis.text(t)))
    out.append(_line("vb-axis", frame.x0, frame.y0, frame.x0, frame.y1))
    step = max(1, math.ceil(17 / slot))
    for i, label in enumerate(shown):
        y = frame.y0 + slot * (i + 0.5)
        out.append(
            f'<rect class="vb-col" data-index="{i}" x="{frame.x0:.1f}" '
            f'y="{frame.y0 + slot * i:.1f}" width="{frame.x1 - frame.x0:.1f}" '
            f'height="{slot:.1f}"/>'
        )
        if i % step == 0:
            out.append(_text("vb-tick", frame.x0 - 6, y + 5, "end", label))
    width = max(slot * 0.8 / group, 0.6)
    for s in model.series:
        for i, (base, top) in enumerate(spans[s.n]):
            a, b = axis.at(base), axis.at(top)
            length = max(abs(a - b), 1.0)
            x = min(a, b) if abs(a - b) >= 1.0 else a - 0.5
            k = 0 if model.stack else s.n
            y = frame.y0 + slot * (i + 0.5) - width * group / 2 + width * k
            out.append(
                f'<rect class="vb-bar vb-mark vb-s{colour(s.n)}" '
                f"{_attrs(model, s, i)}{_outline(s)} "
                f'x="{x:.1f}" y="{y:.1f}" width="{length:.1f}" height="{width:.1f}"/>'
            )
    return Drawing("".join(out), W, height, count > DENSE_POINTS)


def scatter(model: Model) -> Drawing:
    """Points on two numeric axes; each point is a mark with its own hit circle."""
    xs = [x for s in model.series for x in s.xs]
    ys = [v for s in model.series for v in s.values]
    wanted = [(t, float(x)) for x, t in model.notes if isinstance(x, int | float)]
    top = events_top(model) or 12.0 + NOTE_ROW * min(2, len(wanted))
    yaxis = make_axis(min(ys), max(ys), H - BOTTOM, top, False, model.decimals)
    left = yaxis.width() + 12
    xaxis = make_axis(min(xs), max(xs), left, W - 14, False, None)
    frame = Frame(left, W - 14, top, H - BOTTOM)
    out = [_grid(frame, {"left": yaxis})]
    out += [
        _text("vb-tick", xaxis.at(t), frame.y1 + 22, "middle", xaxis.text(t))
        for t in xaxis.ticks
    ]
    inside = [
        (t, xaxis.at(x)) for t, x in wanted if xaxis.ticks[0] <= x <= xaxis.ticks[-1]
    ]
    out.append(_value_events(model, xaxis, frame, top) or _notes(inside, frame, top))
    for s in model.series:
        for i, (x, y) in enumerate(zip(s.xs, s.values, strict=True)):
            px, py = xaxis.at(x), yaxis.at(y)
            hit = f'<circle class="vb-hit" cx="{px:.1f}" cy="{py:.1f}" r="14"/>'
            sym = symbol(marker_of(s.n), px, py, 4.5, "")
            cls = f"vb-dot vb-mark vb-s{colour(s.n)}"
            out.append(f'<g class="{cls}" {_attrs(model, s, i)}>{hit}{sym}</g>')
    return Drawing("".join(out), W, H, False)


def _value_events(model: Model, xaxis: Axis, frame: Frame, top: float) -> str:
    """Bands and markers on a numeric x axis; empty when the chart has no events."""
    spans = []
    for event in model.events:
        x0 = xaxis.at(float(event.start))  # type: ignore[arg-type]
        x1 = x0 if event.end is None else xaxis.at(float(event.end))  # type: ignore[arg-type]
        spans.append((event, x0, x1))
    return draw_events(model, spans, frame.x0, frame.x1, top, frame.y1) if spans else ""


def sparkline(model: Model) -> Drawing:
    """A bare line with no axes: the first series only, hit columns for reading."""
    s = model.series[0]
    low, high = min(s.values), max(s.values)
    if high == low:
        low, high = low - 1, high + 1
    count = len(s.values)
    frame = Frame(6.0, SPARK_W - 6, 6.0, SPARK_H - 6)
    slot = (frame.x1 - frame.x0) / max(count - 1, 1)
    pts = [
        (
            frame.x0 + slot * i if count > 1 else SPARK_W / 2,
            frame.y1 - (v - low) / (high - low) * (frame.y1 - frame.y0),
        )
        for i, v in enumerate(s.values)
    ]
    cols = "".join(
        f'<rect class="vb-col" data-index="{i}" x="{max(0.0, x - slot / 2):.1f}" '
        f'y="0" width="{min(SPARK_W, x + slot / 2) - max(0.0, x - slot / 2):.1f}" '
        f'height="{SPARK_H:g}"/>'
        for i, (x, _) in enumerate(pts)
    )
    marks = "".join(
        _dot(model, s, i, x, y, i == count - 1) for i, (x, y) in enumerate(pts)
    )
    return Drawing(cols + _poly("line", s, pts, s.name) + marks, SPARK_W, SPARK_H, True)


def donut(model: Model) -> Drawing:
    """A ring of slices; each slice is a series so the legend toggles it."""
    cx, cy, outer, inner = W / 2, H / 2, 80.0, 50.0
    total = sum(s.values[0] for s in model.series)
    out = []
    angle = -math.pi / 2
    for s in model.series:
        share = s.values[0] / total if total else 0.0
        if share <= 0:
            continue
        sweep = min(share, 0.99999) * 2 * math.pi
        a0, a1 = angle, angle + sweep
        angle = a1
        large = 1 if sweep > math.pi else 0
        p = lambda r, a: f"{cx + r * math.cos(a):.1f} {cy + r * math.sin(a):.1f}"  # noqa: E731
        d = (
            f"M{p(outer, a0)}A{outer:g} {outer:g} 0 {large} 1 {p(outer, a1)}"
            f"L{p(inner, a1)}A{inner:g} {inner:g} 0 {large} 0 {p(inner, a0)}Z"
        )
        cls = f"vb-slice vb-mark vb-s{colour(s.n)}"
        out.append(f'<path class="{cls}" {_attrs(model, s, 0)} d="{d}"/>')
        mid = (a0 + a1) / 2
        if share >= 0.04:
            mx, my = (
                cx + (inner + outer) / 2 * math.cos(mid),
                cy + (inner + outer) / 2 * math.sin(mid),
            )
            key = (
                f'data-series="{s.n}" data-marker="{marker_of(s.n)}" '
                f'data-dash="{dash_of(s.n)}" aria-label="{esc(s.name)}"'
            )
            out.append(symbol(marker_of(s.n), mx, my, 4.5, "vb-slice-key", key))
            tx, ty = (
                cx + (outer + 12) * math.cos(mid),
                cy + (outer + 12) * math.sin(mid),
            )
            anchor = (
                "start"
                if math.cos(mid) > 0.2
                else "end"
                if math.cos(mid) < -0.2
                else "middle"
            )
            out.append(
                _text(
                    "vb-pct",
                    tx,
                    ty + 5,
                    anchor,
                    f"{share * 100:.0f}%",
                    f' data-series="{s.n}"',
                )
            )
    out.append(
        _text("vb-center", cx, cy + 5, "middle", show(model, model.series[0], total))
    )
    return Drawing("".join(out), W, H, False)


def draw(model: Model) -> Drawing:
    if model.kind == "donut":
        return donut(model)
    if model.kind == "scatter":
        return scatter(model)
    if model.kind == "sparkline":
        return sparkline(model)
    if model.horizontal:
        return horizontal_bars(model)
    return categorical(model)
