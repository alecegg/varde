"""Chart events: bands and markers, validation, text forms and interaction."""

from __future__ import annotations

import itertools
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import check_props
from varde_learn.docs.pages.blocks.chart_notes import MAX_NOTES
from varde_learn.docs.pages.blocks_render.chart_events import hatch_path, place_pins
from varde_learn.docs.pages.blocks_render.chart_model import (
    Event,
    build_model,
    copy_text,
)
from varde_learn.docs.pages.blocks_render.charts import render_chart
from varde_learn.docs.pages.lines import parse_lines
from varde_learn.docs.pages.serve import PageServer

LABELS = ["a", "b", "c", "d"]
LINE: dict[str, Any] = {
    "kind": "line",
    "labels": LABELS,
    "series": [{"name": "s", "values": [1, 3, 2, 4]}],
}
SCATTER: dict[str, Any] = {
    "kind": "scatter",
    "series": [{"name": "s", "x": [1, 2, 3, 4], "values": [1, 3, 2, 4]}],
}
BAND = {"from": "b", "to": "c", "label": "rollout", "tone": "warning"}
MARK = {"x": "d", "label": "fix", "tone": "success"}


def rules(data: dict[str, Any]) -> set[str]:
    return {f.rule for f in check_props("chart", data, 1)}


def with_notes(base: dict[str, Any], *notes: dict[str, Any]) -> dict[str, Any]:
    return {**base, "notes": list(notes)}


@pytest.mark.parametrize("base", [LINE, {**LINE, "kind": "bar"}])
def test_band_and_marker_draw_on_line_and_bar(base: dict[str, Any]) -> None:
    out = render_chart(with_notes(base, BAND, MARK))
    assert out.count('class="vb-band"') == 1 and "vb-hatch" in out
    assert out.count("vb-ev-line") == 1 and "vb-ev-glyph" in out
    assert out.count("vb-ev-pin") == 2 and "NaN" not in out and "nan" not in out


def test_band_and_marker_draw_on_scatter() -> None:
    band = {"from": 2, "to": 3, "label": "slow", "tone": "risk"}
    out = render_chart(with_notes(SCATTER, band, {"x": 4, "label": "m"}))
    assert out.count('class="vb-band"') == 1 and out.count("vb-ev-line") == 1
    assert "nan" not in out.lower()


def test_tones_differ_by_hatch_not_colour_alone() -> None:
    notes = [
        {"from": "a", "to": "b", "label": t, "tone": t}
        for t in ("info", "decision", "risk", "warning", "success")
    ]
    out = render_chart(with_notes(LINE, *notes))
    paths = re.findall(r'class="vb-hatch" d="([^"]+)"', out)
    assert len(paths) == 5 and len(set(paths)) == 5


def test_band_covering_all_labels_and_one_slot_are_allowed() -> None:
    all_labels = {"from": "a", "to": "d", "label": "all"}
    one = {"from": "b", "to": "b", "label": "one"}
    assert rules(with_notes(LINE, all_labels, one)) == set()


def test_invalid_ranges_unknown_tone_and_mixed_keys_are_faulted() -> None:
    backwards = {"from": "c", "to": "b", "label": "n"}
    assert rules(with_notes(LINE, backwards)) == {"note-range"}
    assert "note-x" in rules(with_notes(LINE, {"from": "zz", "to": "b", "label": "n"}))
    assert "note-tone" in rules(with_notes(LINE, {**BAND, "tone": "loud"}))
    assert "note-tone" in rules(with_notes(LINE, {**MARK, "tone": "loud"}))
    assert "note-mixed" in rules(
        with_notes(LINE, {"x": "a", "from": "a", "label": "n"})
    )
    assert "missing-key" in rules(with_notes(LINE, {"from": "a", "label": "n"}))
    assert "missing-key" in rules(with_notes(LINE, {"label": "n"}))
    assert "unknown-key" in rules(with_notes(LINE, {**BAND, "colour": "red"}))


def test_scatter_ranges_must_be_ordered_wide_and_inside_the_data() -> None:
    def band(a: float, b: float) -> dict[str, Any]:
        return {"from": a, "to": b, "label": "n"}

    assert rules(with_notes(SCATTER, band(1, 4))) == set()
    assert rules(with_notes(SCATTER, band(3, 3))) == {"note-range"}
    assert rules(with_notes(SCATTER, band(3, 2))) == {"note-range"}
    assert rules(with_notes(SCATTER, band(0, 2))) == {"note-range"}
    assert rules(with_notes(SCATTER, band(2, 9))) == {"note-range"}
    assert "note-x" in rules(with_notes(SCATTER, {"from": "a", "to": 2, "label": "n"}))


def test_twelve_notes_are_allowed_and_a_thirteenth_is_not() -> None:
    twelve = [{"x": "a", "label": f"n{i}"} for i in range(MAX_NOTES)]
    assert rules(with_notes(LINE, *twelve)) == set()
    assert "too-many" in rules(with_notes(LINE, *twelve, {"x": "a", "label": "x"}))


def test_old_notes_render_exactly_as_before() -> None:
    out = render_chart(with_notes(LINE, {"x": "b", "label": "peak"}))
    assert 'class="vb-note"' in out and "<li>b: peak</li>" in out
    assert "vb-events" not in out and "vb-ev-" not in out
    assert build_model(with_notes(LINE, {"x": "b", "label": "p"})).events == []


def test_events_list_table_rows_and_csv_carry_every_event() -> None:
    props = with_notes(LINE, BAND, MARK)
    out = render_chart(props)
    items = re.findall(r'<li class="vb-ev ', out)
    assert len(items) == 2
    assert "(band, b to c, warning)" in out and "(marker, at d, success)" in out
    assert (
        "<h5>Events</h5>" in out and ">rollout</th><td>band</td><td>b to c</td>" in out
    )
    csv = copy_text(build_model(props))
    assert "event,kind,where,tone" in csv
    assert "rollout,band,b to c,warning" in csv and "fix,marker,at d,success" in csv
    scatter = copy_text(
        build_model(with_notes(SCATTER, {"from": 2, "to": 3, "label": "s"}))
    )
    assert "s,band,2 to 3,info" in scatter


def test_text_alternative_is_plural_correct() -> None:
    one = render_chart(with_notes(LINE, MARK))
    two = render_chart(with_notes(LINE, BAND, MARK))
    assert "1 event is listed under the chart." in one
    assert "2 events are listed under the chart." in two
    assert '<p class="vb-alt">' in two


def test_hostile_labels_are_escaped() -> None:
    hostile = "<script>alert(1)</script>"
    out = render_chart(
        with_notes(LINE, {"from": "a", "to": "b", "label": hostile, "tone": "risk"})
    )
    assert hostile not in out and "&lt;script&gt;" in out
    assert "<button" not in out and "style=" not in out


def test_hidden_series_do_not_hide_events() -> None:
    out = render_chart(with_notes(LINE, BAND, MARK))
    for tag in re.findall(r'<g class="vb-ev [^"]*"[^>]*>', out):
        assert "data-series" not in tag


def test_pins_never_vanish_and_labels_thin_out() -> None:
    events = [Event(n, "long label here", "a", None, "info") for n in range(1, 13)]
    spans = [(e, 100.0, 100.0) for e in events]
    pins = place_pins(spans, 20.0, 340.0, 3)
    assert len(pins) == 12 and sum(1 for p in pins if p.label) < 12
    assert all(20 <= p.x <= 340 for p in pins)


def test_hatch_paths_stay_inside_the_rect() -> None:
    for style in "/\\x-|":
        nums = [
            float(n)
            for n in re.findall(r"-?\d+\.?\d*", hatch_path(10, 20, 50, 60, style))
        ]
        xs, ys = nums[0::2], nums[1::2]
        assert xs and min(xs) >= 9.9 and max(xs) <= 50.1
        assert min(ys) >= 19.9 and max(ys) <= 60.1


def test_stress_fixture_renders_without_nan_and_every_event_is_listed() -> None:
    path = (
        Path(__file__).parent / "fixtures" / "widgets" / "rich-chart-events-stress.md"
    )
    blocks = re.findall(r"```ui\n(.*?)```", path.read_text(encoding="utf-8"), re.DOTALL)
    total = 0
    for body in blocks:
        for st in parse_lines(body).statements:
            assert check_props("chart", st.props, 1) == []
            out = render_chart(st.props)
            notes: list[Any] = list(st.props["notes"])  # type: ignore[call-overload]
            total += len(notes)
            assert "nan" not in out.lower() and "<script" not in out
            assert out.count('<li class="vb-ev ') == len(notes)
    assert total >= 12 + 6 + 4


# ---- Chromium (slow tier) ---------------------------------------------------

DOC = """# Events

```ui id=c
c = chart(
  kind: "line",
  title: "Trend",
  labels: ["A", "B", "C", "D"],
  series: [{"name": "first", "values": [1, 2, 3, 4]}],
  notes: [
    {"from": "B", "to": "C", "label": "rollout", "tone": "warning"},
    {"x": "D", "label": "fix", "tone": "success"},
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
    shared_page.wait_for_selector(".vb-ev-btn")
    shared_page.wait_for_timeout(600)  # the live refresh rebuilds widgets once
    shared_page.wait_for_selector(".vb-ev-btn")
    yield shared_page
    assert problems == []
    shared_page.goto("about:blank")
    server.shutdown()
    server.server_close()
    thread.join(5)


def readout(page: Any) -> str:
    return page.locator(".vb-readout").inner_text()


@pytest.mark.slow
def test_interact_focus_order_puts_events_after_the_data_points(open_page: Any) -> None:
    page = open_page
    page.locator(".vb-plot").focus()
    seen = []
    for _ in range(4):
        page.keyboard.press("Tab")
        seen.append(page.evaluate("document.activeElement.className"))
    first = [c for c in seen if "vb-ev-btn" in c]
    assert first and "vb-ev-btn" in seen[seen.index(first[0])]
    assert seen.index(first[0]) >= 1  # after the series toggle, not before the plot


@pytest.mark.slow
def test_interact_focus_and_hover_show_tooltip_and_live_readout(open_page: Any) -> None:
    page = open_page
    buttons = page.locator(".vb-ev-btn")
    buttons.nth(0).focus()
    assert "rollout" in readout(page) and "band, B to C, warning" in readout(page)
    assert page.locator(".vb-tip").count() == 1
    assert page.locator('svg [data-event="1"].vb-on').count() >= 1
    buttons.nth(1).hover()
    assert "fix" in readout(page) and "marker, at D" in readout(page)
    page.locator(".vb-ev-pin").first.hover()
    assert "rollout" in readout(page)
    page.locator(".vb-ev-pin").nth(1).tap()
    assert "fix" in readout(page)


@pytest.mark.slow
def test_interact_escape_clears_the_event_readout(open_page: Any) -> None:
    page = open_page
    page.locator(".vb-ev-btn").first.focus()
    assert page.locator(".vb-tip").count() == 1
    page.keyboard.press("Escape")
    assert page.locator(".vb-tip").count() == 0 and "Hover" in readout(page)


@pytest.mark.slow
def test_interact_event_buttons_are_44px_and_do_not_overlap(open_page: Any) -> None:
    page = open_page
    for width in (900, 320):
        page.set_viewport_size({"width": width, "height": 700})
        boxes = [b.bounding_box() for b in page.locator(".vb-ev-btn").all()]
        assert all(b["width"] >= 44 and b["height"] >= 44 for b in boxes), boxes
        for upper, lower in itertools.pairwise(boxes):
            assert upper["y"] + upper["height"] <= lower["y"], (upper, lower)
    page.set_viewport_size({"width": 900, "height": 700})


@pytest.mark.slow
def test_interact_no_clipping_at_320_and_labels_collapse_to_pins(
    open_page: Any,
) -> None:
    page = open_page
    page.set_viewport_size({"width": 320, "height": 700})
    assert page.locator(".vb-ev-text").first.is_hidden()
    assert page.locator(".vb-ev-pin").first.is_visible()
    page.locator(".vb-ev-btn").first.hover()
    inside = page.evaluate(
        """() => {
          const s = document.querySelector('svg.vb-chart').getBoundingClientRect();
          const t = document.querySelector('.vb-tip').getBoundingClientRect();
          return [t.left - s.left, s.right - t.right,
            t.top - s.top, s.bottom - t.bottom];
        }"""
    )
    assert all(gap >= -0.5 for gap in inside), inside
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.set_viewport_size({"width": 900, "height": 700})
