"""Block type for numbers: chart."""

import math

from varde_learn.docs.pages.blocks.chart_notes import note_faults
from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    is_number,
    list_of,
    str_field,
    tables,
    tables_fault,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec

_CHART_KINDS = ("bar", "line", "area", "scatter", "donut", "sparkline", "combo")
MAX_SERIES = 12
MAX_POINTS = 500
_OPTIONAL = {"title", "unit", "desc", "notes", "stack", "horizontal", "decimals"}
_OPTIONAL |= {"right_unit", "labels"}
_SERIES_OPTIONAL = {"x", "axis", "type"}


def _bool_faults(data: dict[str, object]) -> list[Fault]:
    faults = [
        Fault("type", f"chart.{key} must be true or false")
        for key in ("stack", "horizontal")
        if key in data and not isinstance(data[key], bool)
    ]
    if data.get("stack") is True and data.get("kind") not in ("bar", "combo"):
        faults.append(Fault("type", "chart.stack applies to bar or combo charts"))
    if data.get("horizontal") is True and data.get("kind") != "bar":
        faults.append(Fault("type", "chart.horizontal applies to bar charts"))
    return faults


def _number_faults(data: dict[str, object]) -> list[Fault]:
    faults = str_field(data, "desc", "chart") + str_field(data, "right_unit", "chart")
    decimals = data.get("decimals")
    if "decimals" in data and not (
        isinstance(decimals, int)
        and not isinstance(decimals, bool)
        and 0 <= decimals <= 6
    ):
        faults.append(
            Fault("type", "chart.decimals must be a whole number from 0 to 6")
        )
    return faults


def _values_faults(
    kind: object, labels: object, series: dict[str, object], where: str
) -> list[Fault]:
    values = series.get("values")
    if "values" not in series:
        return []
    if not (
        isinstance(values, list)
        and values
        and all(is_number(v) and math.isfinite(v) for v in values)
    ):
        return [Fault("type", f"{where}.values must be a non-empty list of numbers")]
    if len(values) > MAX_POINTS:
        return [Fault("too-many", f"{where}.values: at most {MAX_POINTS} numbers")]
    if kind == "donut" and any(v < 0 for v in values):
        return [Fault("donut-negative", f"{where}.values must not be negative")]
    if kind != "scatter" and isinstance(labels, list) and len(values) != len(labels):
        message = (
            f"{where}.values has {len(values)} numbers, "
            f"expected {len(labels)} (one per label)"
        )
        return [Fault("series-length", message)]
    return []


def _scatter_faults(series: dict[str, object], where: str) -> list[Fault]:
    xs, values = series.get("x"), series.get("values")
    if not (
        isinstance(xs, list) and all(is_number(v) and math.isfinite(v) for v in xs)
    ):
        return [Fault("type", f"{where}.x must be a list of numbers, one per value")]
    if isinstance(values, list) and len(xs) != len(values):
        return [
            Fault(
                "series-length",
                f"{where}.x has {len(xs)} numbers, expected {len(values)}",
            )
        ]
    return []


def _series_faults(data: dict[str, object]) -> list[Fault]:
    kind, labels = data.get("kind"), data.get("labels")
    items = tables(data, "series", "chart")
    faults: list[Fault] = []
    if len(items) > MAX_SERIES:
        faults.append(Fault("too-many", f"chart.series: at most {MAX_SERIES} series"))
    if kind in ("donut", "sparkline") and len(items) > 1:
        faults.append(Fault("type", f"chart: a {kind} takes one series"))
    for n, series in enumerate(items, 1):
        where = f"series[{n}]"
        faults += check_keys(series, {"name", "values"}, _SERIES_OPTIONAL, where)
        faults += str_field(series, "name", where)
        faults += _values_faults(kind, labels, series, where)
        if kind == "scatter":
            faults += _scatter_faults(series, where)
        elif "x" in series:
            faults.append(Fault("type", f"{where}.x applies to scatter charts"))
        if "axis" in series and (
            kind != "combo" or series["axis"] not in ("left", "right")
        ):
            faults.append(
                Fault("type", f"{where}.axis is left or right, on combo charts")
            )
        if "type" in series and (
            kind != "combo" or series["type"] not in ("bar", "line")
        ):
            faults.append(
                Fault("type", f"{where}.type is bar or line, on combo charts")
            )
    return faults


def validate_chart(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"kind", "series"}, _OPTIONAL, "chart")
    faults += str_field(data, "title", "chart") + str_field(data, "unit", "chart")
    faults += _number_faults(data) + _bool_faults(data) + note_faults(data)
    if "kind" in data and data["kind"] not in _CHART_KINDS:
        faults.append(Fault("type", f"chart: kind must be one of {list(_CHART_KINDS)}"))
    if "labels" in data:
        faults += list_of(data["labels"], "chart.labels")
    elif data.get("kind") != "scatter":
        faults.append(Fault("missing-key", "chart: missing required key 'labels'"))
    faults += tables_fault(data, "series", "chart") + _series_faults(data)
    return faults


CHART = BlockSpec(
    "chart",
    "A bar, line, area, scatter, donut, sparkline or combo chart from numbers",
    (
        "kind    bar, line, area, scatter, donut, sparkline or combo",
        "labels  list of x labels (donut: slice names; scatter: omit)",
        "title, unit, desc  optional text; desc is a one-sentence summary",
        "right_unit  optional unit of the right axis (combo)",
        "decimals  optional digits after the point, 0 to 6",
        "stack, horizontal  optional true or false (bar; stack also combo)",
        "notes: optional list, up to 12, of markers and bands; x, from and to are",
        "  labels (scatter: numbers); a band's from is not after its to",
        "  x      marker position;  label  required text;  tone  info (default),",
        "         decision, risk, warning or success",
        "  from, to  band ends instead of x (scatter: from below to, inside the data)",
        "series: list of {name, values}, one per series (up to 12)",
        "  name    series name",
        "  values  list of numbers, one per label",
        "  x       scatter only: list of numbers, one per value",
        "  axis, type  combo only: axis left or right; type bar or line",
    ),
    r"""chart = chart(
  kind: "bar",
  title: "Latency",
  unit: "ms",
  desc: "p95 latency fell by about half after the cache change.",
  labels: ["before", "after"],
  series: [
    {"name": "p50", "values": [120, 80]},
    {"name": "p95", "values": [400, 210]},
  ],
  notes: [
    {"x": "after", "label": "cache"},
    {"from": "before", "to": "after", "label": "rollout", "tone": "warning"},
  ],
)
""",
    validate_chart,
)
