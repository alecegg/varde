"""Charts as server-rendered SVG with a legend and a data table fallback.

The drawing is `chart_draw`, the numbers and text forms are `chart_model`; this
module assembles the block. `static/chart.js` adds the tooltip, the live
readout, the legend toggles and keyboard reading on top of the same markup.
"""

from varde_learn.docs.pages.blocks_render.chart_draw import draw, symbol
from varde_learn.docs.pages.blocks_render.chart_events import (
    events_list,
    events_sentence,
    events_table,
)
from varde_learn.docs.pages.blocks_render.chart_model import (
    Model,
    Series,
    build_model,
    colour,
    copy_text,
    csv_rows,
    dash_of,
    marker_of,
    show,
    summary,
)
from varde_learn.docs.pages.blocks_render.chart_scale import fmt
from varde_learn.docs.pages.blocks_render.common import card, data_scroll, esc
from varde_learn.docs.pages.blocks_render.svg import copy_attr, svg_root

__all__ = ["copy_text", "fmt", "render_chart"]


def _key(s: Series) -> str:
    """A legend swatch that differs by shape and dash, not colour alone."""
    c = f"vb-s{colour(s.n)}"
    dash = dash_of(s.n)
    if s.kind in ("bar", "slice", "area"):
        body = f'<rect class="vb-bar {c}" x="2" y="2" width="24" height="10"/>'
    else:
        dashed = f' stroke-dasharray="{dash}"' if dash else ""
        body = f'<line class="vb-line {c}" x1="1" y1="7" x2="27" y2="7"{dashed}/>'
    mark = symbol(marker_of(s.n), 14, 7, 3.5, f"vb-key-mark {c}")
    return (
        f'<svg class="vb-key" viewBox="0 0 28 14" aria-hidden="true" '
        f'focusable="false">{body}{mark}</svg>'
    )


def _legend(model: Model) -> str:
    if model.kind == "sparkline":
        return ""
    items = "".join(
        f'<li class="vb-s{colour(s.n)}" data-series="{s.n}" '
        f'data-marker="{marker_of(s.n)}" data-dash="{dash_of(s.n)}">'
        f'{_key(s)}<span class="vb-name">{esc(s.name)}</span></li>'
        for s in model.series
    )
    return f'<ul class="vb-legend">{items}</ul>'


def _cells(model: Model) -> tuple[str, list[str]]:
    """Table header row and body rows; series cells carry `data-series`."""
    if model.kind in ("scatter", "donut"):
        head = "".join(f"<th>{esc(c)}</th>" for c in csv_rows(model)[0])
        rows = []
        for s in model.series:
            cells = (
                (
                    [s.name, fmt(s.xs[i]), show(model, s, s.values[i])]
                    for i in range(len(s.values))
                )
                if model.kind == "scatter"
                else ([[s.name, show(model, s, s.values[0])]])
            )
            rows += [
                f'<tr data-series="{s.n}">'
                + "".join(f"<td>{esc(c)}</td>" for c in row)
                + "</tr>"
                for row in cells
            ]
        return head, rows
    head = "<th>Label</th>" + "".join(
        f'<th data-series="{s.n}">{esc(s.name)}</th>' for s in model.series
    )
    rows = [
        f'<tr><th scope="row">{esc(label)}</th>'
        + "".join(
            f'<td data-series="{s.n}">{esc(show(model, s, s.values[i]))}</td>'
            for s in model.series
        )
        + "</tr>"
        for i, label in enumerate(model.labels)
    ]
    return head, rows


def _data(model: Model, desc: str) -> str:
    head, rows = _cells(model)
    grid = (
        f'<table class="vb-data-grid"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    grid = data_scroll(grid, "Data table")
    notes = ""
    if model.events:
        notes = events_table(model)
    elif model.notes:
        items = "".join(f"<li>{esc(x)}: {esc(text)}</li>" for x, text in model.notes)
        notes = f'<h5>Notes</h5><ul class="vb-notes">{items}</ul>'
    return (
        f'<details class="vb-data"><summary>Data table</summary>'
        f'<p class="vb-alt">{esc(desc)}</p>{grid}{notes}</details>'
    )


def _events(model: Model) -> str:
    return events_list(model) if model.events else ""


def _heading(model: Model, props: dict[str, object]) -> str:
    if "title" not in props:
        return ""
    units = [u for u in (model.unit, model.right_unit) if u]
    unit = f" ({esc(' / '.join(units))})" if units else ""
    return esc(model.title) + unit


def render_chart(data: dict[str, object]) -> str:
    model = build_model(data)
    drawing = draw(model)
    desc = model.desc or summary(model)
    if model.events:
        desc = f"{desc} {events_sentence(len(model.events))}"
    cls = "vb-chart" + (" vb-dense" if drawing.dense else "")
    cls += " vb-spark" if model.kind == "sparkline" else ""
    svg = svg_root(
        model.title, desc, (0, 0, drawing.width, drawing.height), drawing.inner, cls
    )
    plot = f'<div class="vb-plot" data-kind="{esc(model.kind)}">{svg}</div>'
    body = card(
        _heading(model, data),
        plot + _legend(model) + _events(model) + _data(model, desc),
    )
    return f'<div class="vb chart"{copy_attr(copy_text(model))}>{body}</div>'
