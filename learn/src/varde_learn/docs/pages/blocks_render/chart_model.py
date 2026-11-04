"""Chart props as plain data, plus the text forms (summary, CSV, readings). Pure."""

from dataclasses import dataclass, field

from varde_learn.docs.pages.blocks_render.chart_scale import fmt, raw
from varde_learn.docs.pages.blocks_render.common import as_dict, as_list
from varde_learn.docs.pages.blocks_render.svg import dash, marker_shape

COLOURS = 6


@dataclass(frozen=True)
class Series:
    n: int
    name: str
    values: list[float]
    xs: list[float]  # scatter x values; empty otherwise
    axis: str  # "left" or "right"
    kind: str  # bar, line, area, scatter or slice


@dataclass(frozen=True)
class Event:
    """One note as an event: a marker at `start`, or a band from `start` to `end`."""

    n: int  # 1-based pin number, the order in the props
    label: str
    start: object  # a label, or a number on a scatter
    end: object | None  # None for a marker
    tone: str

    @property
    def kind(self) -> str:
        return "marker" if self.end is None else "band"


@dataclass(frozen=True)
class Model:
    kind: str
    title: str
    desc: str
    unit: str
    right_unit: str
    decimals: int | None
    labels: list[str]
    series: list[Series]
    notes: list[tuple[object, str]]
    stack: bool
    horizontal: bool
    events: list[Event] = field(default_factory=list)


def colour(n: int) -> int:
    return n % COLOURS


def marker_of(n: int) -> str:
    return marker_shape(n + n // COLOURS)


def dash_of(n: int) -> str:
    return dash(n + n // COLOURS)


def _kind_of(chart: str, raw_series: dict[str, object], first: bool) -> str:
    if chart == "combo":
        return str(raw_series.get("type", "bar" if first else "line"))
    return {"sparkline": "line"}.get(chart, chart)


def _events(props: dict[str, object]) -> list[Event]:
    """Every note as an event, only when a note is a band or has a tone."""
    notes = [as_dict(n) for n in as_list(props.get("notes"))]
    if not any("from" in n or "tone" in n for n in notes):
        return []
    return [
        Event(
            i,
            str(n["label"]),
            n["x"] if "x" in n else n["from"],
            None if "x" in n else n["to"],
            str(n.get("tone", "info")),
        )
        for i, n in enumerate(notes, 1)
    ]


def build_model(props: dict[str, object]) -> Model:
    chart = str(props["kind"])
    raw_series = [as_dict(s) for s in as_list(props["series"])]
    labels = [str(x) for x in as_list(props.get("labels"))]
    series = [
        Series(
            n,
            str(s["name"]),
            [float(v) for v in as_list(s["values"])],
            [float(v) for v in as_list(s.get("x"))],
            str(s.get("axis", "left")),
            _kind_of(chart, s, n == 0),
        )
        for n, s in enumerate(raw_series)
    ]
    if chart == "donut":
        values = series[0].values
        series = [
            Series(i, labels[i], [v], [], "left", "slice") for i, v in enumerate(values)
        ]
    notes = [
        (as_dict(n)["x"], str(as_dict(n)["label"]))
        for n in as_list(props.get("notes"))
        if "x" in as_dict(n)
    ]
    decimals = props.get("decimals")
    return Model(
        chart,
        str(props.get("title", "chart")),
        str(props.get("desc", "")),
        str(props.get("unit", "")),
        str(props.get("right_unit", "")),
        decimals if isinstance(decimals, int) else None,
        labels,
        series,
        notes,
        props.get("stack") is True,
        props.get("horizontal") is True,
        _events(props),
    )


def unit_of(model: Model, series: Series) -> str:
    return model.right_unit if series.axis == "right" else model.unit


def show(model: Model, series: Series, value: float) -> str:
    return f"{fmt(value, model.decimals)} {unit_of(model, series)}".strip()


def point_label(model: Model, series: Series, i: int) -> str:
    if series.kind == "scatter":
        return f"x {fmt(series.xs[i])}"
    return model.labels[i] if i < len(model.labels) else str(i + 1)


def reading(model: Model, series: Series, i: int) -> str:
    """The live-region text for one point: series / label / value."""
    value = show(model, series, series.values[i])
    return f"{series.name} / {point_label(model, series, i)} / {value}"


def position(model: Model, value: object) -> str:
    """An event end as text: a label, or a formatted number on a scatter."""
    if model.kind == "scatter" and isinstance(value, int | float):
        return fmt(float(value))
    return str(value)


def where(model: Model, event: Event) -> str:
    start = position(model, event.start)
    if event.end is None:
        return f"at {start}"
    return f"{start} to {position(model, event.end)}"


def event_rows(model: Model) -> list[list[str]]:
    """Each event as label, kind, range or position, tone: the table and CSV rows."""
    return [[e.label, e.kind, where(model, e), e.tone] for e in model.events]


def summary(model: Model) -> str:
    """One sentence for the SVG `<desc>` when the props give none."""
    values = [v for s in model.series for v in s.values]
    low, high = fmt(min(values), model.decimals), fmt(max(values), model.decimals)
    kind = {"sparkline": "Sparkline", "combo": "Bar and line chart"}.get(
        model.kind, f"{model.kind.capitalize()} chart"
    )
    count = len(model.series)
    noun = "slice" if model.kind == "donut" else "series"
    noun = noun if count == 1 else ("slices" if noun == "slice" else "series")
    unit = f" {model.unit}" if model.unit else ""
    return f"{kind} with {count} {noun}; values run from {low} to {high}{unit}."


def _csv_cell(text: str) -> str:
    if any(c in text for c in ',"\n\r'):
        return '"' + text.replace('"', '""') + '"'
    return text


def csv_rows(model: Model) -> list[list[str]]:
    """The data as rows of text: the table fallback and the Copy entry share it."""
    if model.kind == "scatter":
        rows = [["series", "x", "y"]]
        for s in model.series:
            rows += [
                [s.name, raw(x), raw(y)] for x, y in zip(s.xs, s.values, strict=True)
            ]
        return rows
    if model.kind == "donut":
        return [["label", "value"]] + [[s.name, raw(s.values[0])] for s in model.series]
    rows = [["label"] + [s.name for s in model.series]]
    for i, label in enumerate(model.labels):
        rows.append([label] + [raw(s.values[i]) for s in model.series])
    return rows


def copy_text(model: Model) -> str:
    rows = csv_rows(model)
    if model.events:
        rows = rows + [["event", "kind", "where", "tone"]] + event_rows(model)
    return "\n".join(",".join(_csv_cell(c) for c in row) for row in rows)
