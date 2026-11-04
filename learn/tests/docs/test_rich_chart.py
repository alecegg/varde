"""The chart component: spec, scales, SVG, text forms and slow-tier interactions."""

from __future__ import annotations

import html
import itertools
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import check_props
from varde_learn.docs.pages.blocks.charts import CHART, MAX_SERIES
from varde_learn.docs.pages.blocks_render.chart_model import build_model, copy_text
from varde_learn.docs.pages.blocks_render.chart_scale import (
    compact,
    fmt,
    nice_ticks,
    thin_step,
)
from varde_learn.docs.pages.blocks_render.charts import render_chart
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.lines import parse_lines
from varde_learn.docs.pages.serve import PageServer

LABELS = ["before", "after"]
SERIES = [
    {"name": "p50", "values": [120, 80]},
    {"name": "p95", "values": [400, 210]},
]
BASE: dict[str, Any] = {"kind": "bar", "labels": LABELS, "series": SERIES, "unit": "ms"}
KINDS = ("bar", "line", "area", "scatter", "donut", "sparkline", "combo")


def props(kind: str, **more: Any) -> dict[str, Any]:
    out: dict[str, Any] = {**BASE, "kind": kind}
    if kind == "scatter":
        out["series"] = [
            {"name": "a", "x": [1, 2], "values": [3, 4]},
            {"name": "b", "x": [2, 5], "values": [1, 6]},
        ]
        out.pop("labels")
    if kind == "donut":
        out["series"] = [{"name": "share", "values": [30, 70]}]
    if kind == "sparkline":
        out["series"] = SERIES[:1]
    if kind == "combo":
        out["series"] = [SERIES[0], {**SERIES[1], "axis": "right"}]
    return {**out, **more}


def numbers(svg: str, names: tuple[str, ...]) -> list[float]:
    pattern = r"\b(?:" + "|".join(names) + r')="(-?[0-9.]+)"'
    return [float(v) for v in re.findall(pattern, svg)]


def rules(data: dict[str, Any]) -> set[str]:
    return {e.rule for e in check_props("chart", data, 1)}


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_validates_and_renders_clean_svg(kind: str) -> None:
    data = props(kind)
    assert rules(data) == set()
    out = render_chart(data)
    assert out.startswith('<div class="vb chart" data-copy="')
    assert " style=" not in out and "<script" not in out
    assert "nan" not in out.lower() and "inf" not in out.lower().replace("info", "")
    svg = out[out.index("<svg") : out.index("</svg>")]
    box = [float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]  # type: ignore[union-attr]
    xs = numbers(svg, ("x", "x1", "x2", "cx"))
    ys = numbers(svg, ("y", "y1", "y2", "cy"))
    assert all(-1 <= x <= box[2] + 1 for x in xs), kind
    assert all(-1 <= y <= box[3] + 1 for y in ys), kind
    assert "<desc>" in svg and 'role="img"' in svg
    assert '<details class="vb-data">' in out and "<table" in out


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_is_registered_and_marks_carry_hooks(kind: str) -> None:
    assert COMPONENTS["chart"].spec is CHART
    data = props(kind)
    assert COMPONENTS["chart"].render(data, None) == render_chart(data)
    marks = re.findall(r'class="[^"]*vb-mark[^"]*"[^>]*>', render_chart(data))
    assert marks
    for mark in marks:
        assert (
            "data-series=" in mark and "data-index=" in mark and "aria-label=" in mark
        )


def test_table_fallback_equals_the_data() -> None:
    out = render_chart(BASE)
    cells = re.findall(r'<td data-series="(\d)">([^<]*)</td>', out)
    by_series = {n: [c for k, c in cells if k == n] for n in ("0", "1")}
    assert by_series == {"0": ["120 ms", "80 ms"], "1": ["400 ms", "210 ms"]}
    assert (
        '<th scope="row">before</th>' in out and '<th data-series="1">p95</th>' in out
    )


def test_scatter_and_donut_tables_list_each_point_and_slice() -> None:
    scatter = render_chart(props("scatter"))
    assert scatter.count('<tr data-series="0">') == 2
    assert scatter.count('<tr data-series="1">') == 2
    donut = render_chart(props("donut"))
    assert '<tr data-series="1"><td>' in donut and "70 ms" in donut


def test_copy_entry_gives_csv_text() -> None:
    out = render_chart(BASE)
    text = html.unescape(re.search(r'data-copy="([^"]*)"', out).group(1))  # type: ignore[union-attr]
    assert text == "label,p50,p95\nbefore,120,400\nafter,80,210"
    tricky = {**BASE, "labels": ['a,"b"', "c"]}
    assert copy_text(build_model(tricky)).splitlines()[1] == '"a,""b""",120,400'
    scatter = copy_text(build_model(props("scatter")))
    assert scatter.splitlines()[:2] == ["series,x,y", "a,1,3"]


def test_donut_copy_lists_slices_by_label() -> None:
    data = {
        "kind": "donut",
        "labels": ["x", "y"],
        "series": [{"name": "s", "values": [1, 2]}],
    }
    assert copy_text(build_model(data)) == "label,value\nx,1\ny,2"


def test_desc_is_the_svg_description_or_a_generated_sentence() -> None:
    given = render_chart({**BASE, "desc": "Latency halves."})
    assert "<desc>Latency halves.</desc>" in given
    made = render_chart(BASE)
    assert re.search(
        r"<desc>Bar chart with 2 series; values run from 80 to 400 ms\.</desc>", made
    )


def test_negative_zero_and_all_equal_ranges_render() -> None:
    negative = render_chart({**BASE, "series": [{"name": "d", "values": [-2, 3]}]})
    assert negative.count("vb-bar") >= 2 and "-2" in negative
    zero = render_chart({**BASE, "series": [{"name": "z", "values": [0, 0]}]})
    flat = render_chart(
        {**BASE, "kind": "line", "series": [{"name": "f", "values": [5, 5]}]}
    )
    for out in (zero, flat):
        assert "nan" not in out.lower() and "<svg" in out
    spark = render_chart(props("sparkline", series=[{"name": "f", "values": [2, 2]}]))
    assert "vb-line" in spark and "nan" not in spark.lower()


def test_stacked_bars_stack_and_horizontal_bars_grow_sideways() -> None:
    stacked = render_chart({**BASE, "stack": True})
    tops = re.findall(
        r'<rect class="vb-bar vb-mark[^>]* y="([0-9.]+)"'
        r' width="[0-9.]+" height="([0-9.]+)"',
        stacked,
    )
    tops = tops[::2]  # the first label's two bars (they are listed series by series)
    assert len(tops) == 2
    (y_a, h_a), (y_b, h_b) = ((float(y), float(h)) for y, h in tops)
    assert abs((y_a + h_a) - y_b) < 0.2 or abs((y_b + h_b) - y_a) < 0.2
    horizontal = render_chart({**BASE, "horizontal": True})
    assert 'class="vb-bar' in horizontal and 'class="vb-col"' in horizontal


def test_combo_has_two_axes_and_notes_draw_a_rule_and_a_label() -> None:
    combo = render_chart(props("combo", right_unit="%", title="T"))
    assert 'text-anchor="start">' in combo and "ms / %" in combo
    assert combo.count('<rect class="vb-bar vb-mark') == 2 and "vb-line" in combo
    noted = render_chart(
        {**BASE, "kind": "line", "notes": [{"x": "after", "label": "patch"}]}
    )
    assert 'class="vb-note"' in noted and ">patch<" in noted
    assert "<li>after: patch</li>" in noted


def test_series_differ_by_colour_marker_and_dash() -> None:
    out = render_chart({**BASE, "kind": "line"})
    keys = re.findall(
        r'<li class="vb-s(\d)" data-series="\d" data-marker="(\w+)"'
        r' data-dash="([^"]*)"',
        out,
    )
    assert (
        len(set(keys)) == 2
        and len({k[1] for k in keys}) == 2
        and len({k[2] for k in keys}) == 2
    )
    twelve = render_chart(
        {
            **BASE,
            "kind": "line",
            "labels": ["a", "b"],
            "series": [{"name": f"s{i}", "values": [i, 1]} for i in range(12)],
        }
    )
    keys = re.findall(
        r'<li class="vb-s(\d)" data-series="\d+" data-marker="(\w+)"'
        r' data-dash="([^"]*)"',
        twelve,
    )
    assert len(keys) == 12 and len(set(keys)) == 12


def test_direct_end_labels_appear_only_where_there_is_room() -> None:
    line = render_chart({**BASE, "kind": "line"})
    assert line.count('class="vb-end"') == 2
    many = render_chart(
        {
            **BASE,
            "kind": "line",
            "series": [{"name": f"s{i}", "values": [i, 1]} for i in range(8)],
        }
    )
    assert 'class="vb-end"' not in many
    longer = render_chart(
        {
            **BASE,
            "kind": "line",
            "series": [
                {"name": "x" * 60, "values": [1, 2]},
                {"name": "y", "values": [2, 1]},
            ],
        }
    )
    assert longer.count('class="vb-end"') in (0, 2)


def test_two_hundred_points_and_twelve_series_render_fast_and_thin_labels() -> None:
    labels = [f"label-{i}" for i in range(200)]
    series = [
        {"name": f"s{k}", "values": [float((i * (k + 1)) % 17) for i in range(200)]}
        for k in range(12)
    ]
    data = {"kind": "line", "labels": labels, "series": series}
    assert rules(data) == set()
    started = time.perf_counter()
    out = render_chart(data)
    assert time.perf_counter() - started < 2.0
    assert "vb-dense" in out and "nan" not in out.lower()
    ticks = re.findall(
        r'class="vb-tick" x="([0-9.]+)" y="2[0-9.]+" text-anchor="middle"', out
    )
    xs = [float(x) for x in ticks]
    assert 0 < len(xs) < 40 and all(b - a >= 60 for a, b in itertools.pairwise(xs))
    assert out.count("<tr>") == 201


def test_text_is_never_below_11px_at_the_narrowest_chart() -> None:
    from varde_learn.docs.pages.blocks_render.chart_draw import W

    css = (
        Path(__file__)
        .parents[2]
        .joinpath("src/varde_learn/docs/pages/static/css/41-chart.css")
    )
    assert "font: 15px" in css.read_text()
    assert 15 * (264 / W) >= 11


def test_every_prop_text_is_escaped() -> None:
    out = render_chart(
        {
            "kind": "line",
            "title": "<t>",
            "unit": "<u>",
            "desc": "<d>",
            "labels": ["<l>", "m"],
            "series": [{"name": "<s>", "values": [1, 2]}],
            "notes": [{"x": "<l>", "label": "<n>"}],
        }
    )
    for raw in ("<t>", "<u>", "<d>", "<l>", "<s>", "<n>"):
        assert raw not in out


def test_served_html_has_no_script_only_controls() -> None:
    out = render_chart(BASE)
    assert (
        "vb-series-toggle" not in out
        and "vb-readout" not in out
        and "<button" not in out
    )
    assert out.count("tabindex") == out.count('role="region"')  # scroll regions only
    assert "<details" in out


def test_nice_ticks_and_number_forms() -> None:
    assert nice_ticks(0, 87) == [0, 20, 40, 60, 80, 100]
    assert nice_ticks(-3, 3)[0] <= -3 and nice_ticks(-3, 3)[-1] >= 3
    assert nice_ticks(5, 5)[0] < 5 < nice_ticks(5, 5)[-1]
    assert (
        nice_ticks(0, 0.3) == [0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3]
        or nice_ticks(0, 0.3)[-1] >= 0.3
    )
    assert fmt(1234.5) == "1,234.5" and fmt(-0.0) == "0" and fmt(3, 2) == "3.00"
    assert (
        compact(12000) == "12k"
        and compact(1_500_000) == "1.5M"
        and compact(950) == "950"
    )
    assert thin_step(10, 100, 40) == 1 and thin_step(200, 1.5, 60) > 20


def test_spec_example_validates_and_every_kind_is_listed() -> None:
    result = parse_lines(CHART.example)
    assert result.errors == []
    assert check_props("chart", result.statements[0].props, 1) == []
    text = "\n".join(CHART.fields)
    assert all(kind in text for kind in KINDS)


def test_old_props_stay_valid_and_new_ones_are_optional() -> None:
    old = {"kind": "line", "labels": ["a"], "series": [{"name": "s", "values": [1]}]}
    assert rules(old) == set()
    assert rules({"kind": "bar", "series": old["series"]}) == {"missing-key"}


def test_validation_names_each_fault() -> None:
    assert "unknown-key" in rules({**BASE, "colour": "red"})
    assert "type" in rules({**BASE, "kind": "pie"})
    assert "type" in rules({**BASE, "decimals": 9}) and "type" in rules(
        {**BASE, "stack": "yes"}
    )
    assert "type" in rules({**BASE, "kind": "line", "stack": True})
    assert "type" in rules({**BASE, "kind": "line", "horizontal": True})
    assert "series-length" in rules({**BASE, "series": [{"name": "s", "values": [1]}]})
    assert "type" in rules({**BASE, "series": [{"name": "s", "values": []}]})
    assert "donut-negative" in rules(
        props("donut", series=[{"name": "s", "values": [1, -1]}])
    )
    assert "type" in rules(props("donut", series=SERIES))
    assert "type" in rules(props("sparkline", series=SERIES))
    assert "type" in rules({**BASE, "series": [{**SERIES[0], "axis": "right"}]})
    assert "type" in rules({**BASE, "series": [{**SERIES[0], "x": [1, 2]}]})
    assert "type" in rules(props("scatter", series=[{"name": "s", "values": [1]}]))
    assert "series-length" in rules(
        props("scatter", series=[{"name": "s", "x": [1, 2], "values": [1]}])
    )
    assert "note-x" in rules({**BASE, "notes": [{"x": "nope", "label": "n"}]})
    assert "note-x" in rules(props("scatter", notes=[{"x": "a", "label": "n"}]))
    assert "too-many" in rules(
        {
            **BASE,
            "labels": ["a"],
            "series": [{"name": f"s{i}", "values": [1]} for i in range(MAX_SERIES + 1)],
        }
    )


# ---- Chromium (slow tier) ---------------------------------------------------

DOC = """# Chart

```ui id=c
c = chart(
  kind: "line",
  title: "Trend",
  unit: "ms",
  labels: ["A", "B", "C", "D"],
  series: [
    {"name": "first", "values": [1, 2, 3, 4]},
    {"name": "second", "values": [4, 3, 2, 1]},
  ],
)
```
"""


@pytest.fixture(scope="module")
def shared_page(browser_session: Any) -> Any:
    page = browser_session.new_page(
        viewport={"width": 900, "height": 700}, has_touch=True
    )
    page.set_default_timeout(10_000)
    return page


@pytest.fixture
def open_page(tmp_path: Path, shared_page: Any) -> Iterator[Any]:
    doc = tmp_path / "plan.md"
    doc.write_text(DOC, encoding="utf-8")
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    problems: list[str] = []
    shared_page.on("pageerror", lambda error: problems.append(str(error)))
    shared_page.goto(f"http://127.0.0.1:{server.port}/")
    shared_page.wait_for_selector(".vb-series-toggle")
    shared_page.wait_for_timeout(600)  # the live refresh rebuilds widgets once
    shared_page.wait_for_selector(".vb-series-toggle")
    yield shared_page
    assert problems == []
    shared_page.goto("about:blank")
    server.shutdown()
    server.server_close()
    thread.join(5)


def readout(page: Any) -> str:
    return page.locator(".vb-readout").inner_text()


@pytest.mark.slow
def test_interact_hover_and_tap_show_a_tooltip_and_a_live_readout(
    open_page: Any,
) -> None:
    page = open_page
    assert page.locator(".vb-readout").get_attribute("aria-live") == "polite"
    page.locator(".vb-col").nth(1).hover()
    assert page.locator(".vb-tip").count() == 1
    assert "B" in readout(page) and "first: 2" in readout(page)
    page.locator(".vb-col").nth(2).tap()
    assert "C" in readout(page) and page.locator(".vb-tip").count() == 1


@pytest.mark.slow
def test_interact_arrow_keys_home_end_and_escape_move_across_points(
    open_page: Any,
) -> None:
    page = open_page
    page.locator(".vb-plot").focus()
    page.keyboard.press("Home")
    assert readout(page).startswith("A")
    page.keyboard.press("ArrowRight")
    assert readout(page).startswith("B")
    page.keyboard.press("End")
    assert readout(page).startswith("D")
    page.keyboard.press("ArrowLeft")
    assert readout(page).startswith("C")
    page.keyboard.press("Escape")
    assert page.locator(".vb-tip").count() == 0 and "Hover" in readout(page)
    assert page.locator(".vb-plot").get_attribute("role") == "region"


@pytest.mark.slow
def test_interact_legend_toggle_hides_a_series_and_the_table_follows(
    open_page: Any,
) -> None:
    page = open_page
    page.locator(".chart .vb-data summary").click()
    toggle = page.locator(".vb-series-toggle").first
    assert toggle.get_attribute("aria-pressed") == "true"
    toggle.click()
    assert toggle.get_attribute("aria-pressed") == "false"
    assert "vb-off" in (
        page.locator('.vb-line[data-series="0"]').get_attribute("class") or ""
    )
    assert page.locator('.vb-data th[data-series="0"]').is_hidden()
    assert page.locator('.vb-data th[data-series="1"]').is_visible()
    toggle.click()
    assert page.locator('.vb-data th[data-series="0"]').is_visible()
    page.locator(".chart .vb-data summary").click()


@pytest.mark.slow
def test_interact_legend_targets_are_at_least_44px(open_page: Any) -> None:
    page = open_page
    for toggle in page.locator(".vb-series-toggle").all():
        box = toggle.bounding_box()
        assert box["width"] >= 44 and box["height"] >= 44, box
    page.set_viewport_size({"width": 320, "height": 700})
    for toggle in page.locator(".vb-series-toggle").all():
        box = toggle.bounding_box()
        assert box["width"] >= 44 and box["height"] >= 44, box
    page.set_viewport_size({"width": 900, "height": 700})


@pytest.mark.slow
def test_interact_tooltip_is_not_clipped_at_320(open_page: Any) -> None:
    page = open_page
    page.set_viewport_size({"width": 320, "height": 700})
    for index in (0, 3):
        page.locator(".vb-col").nth(index).hover()
        inside = page.evaluate(
            """() => {
              const s = document.querySelector('svg.vb-chart').getBoundingClientRect();
              const t = document.querySelector('.vb-tip').getBoundingClientRect();
              return [t.left - s.left, s.right - t.right,
                t.top - s.top, s.bottom - t.bottom];
            }"""
        )
        assert all(gap >= -0.5 for gap in inside), inside
    page.set_viewport_size({"width": 900, "height": 700})
