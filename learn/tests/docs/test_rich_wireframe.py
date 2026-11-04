"""The wireframe and ui-states components: server SVG, schema, text alternative,
Copy text and interactions."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages import blocks
from varde_learn.docs.pages.blocks import check_props
from varde_learn.docs.pages.blocks.screens import KINDS, SURFACES
from varde_learn.docs.pages.blocks_render import screens
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.blocks_render.screens import (
    copy_text,
    render_ui_states,
    render_wireframe,
)
from varde_learn.docs.pages.render import render_page
from varde_learn.docs.pages.serve import PageServer

PROPS: dict[str, Any] = {
    "title": "Orders <b>list</b>",
    "surface": "browser",
    "grid": ["HHHH", "SSLL", "SSLL", "FFFF"],
    "regions": {"H": "header", "S": "filters", "L": "order list", "F": "footer"},
    "kinds": {"H": "nav", "S": "input", "L": "list"},
    "notes": [
        {"region": "S", "text": "Stays in the URL"},
        {"region": "L", "text": "50 rows <i>at a time</i>"},
        {"region": "L", "text": "Retry on failure"},
    ],
}
OLD: dict[str, Any] = {
    "title": "Plain",
    "grid": ["AB"],
    "regions": {"A": "a", "B": "b"},
}
FIXTURES = Path(__file__).parent / "fixtures" / "widgets"
DOC = (
    "# Wire\n\n```ui id=wire\n"
    'wire = wireframe(title: "Orders", grid: ["HHHH", "SSLL", "SSLL"], '
    'regions: {"H": "header", "S": "filters", "L": "order list"}, '
    'kinds: {"S": "input"}, '
    'notes: [{"region": "S", "text": "Stays in the URL"}, '
    '{"region": "L", "text": "Loads 50 at a time"}])\n```\n\n'
    '```ui id=states\nstates = ui-states(screen: "Orders", '
    'empty: {"shows": "Nothing yet"}, loading: {"shows": "Skeleton"}, '
    'error: {"shows": "Retry"})\n```\n'
)


def rules(props: dict[str, Any]) -> list[str]:
    return [f.rule for f in blocks.check_props("wireframe", props, 1)]


def test_server_html_has_svg_notes_table_and_copy_text() -> None:
    html = render_wireframe(PROPS)
    assert 'class="vb wireframe"' in html and "data-copy=" in html
    assert html.count('class="vw-region ') == 4
    assert html.count('class="vw-pin"') == 3 and 'class="vw-notes"' in html
    assert "Regions as text" in html and "<table" in html
    assert "style=" not in html and "<script" not in html
    assert "<b>list</b>" not in html and "&lt;b&gt;list&lt;/b&gt;" in html
    assert "<i>at a time</i>" not in html


def test_each_kind_gets_its_own_hatch_pattern_and_label() -> None:
    html = render_wireframe(PROPS)
    ids = set(re.findall(r'<pattern id="(vw-[0-9a-f]+-\w+)"', html))
    assert len(ids) == 3
    for kind in ("nav", "input", "list"):
        assert f"[{kind}]" in html
    assert html.count('fill="url(#vw-') == 3
    assert set(screens._KIND_PATTERN) == set(KINDS)
    marks = {(t, m) for t, m in screens._KIND_PATTERN.values()}
    assert len(marks) == len(KINDS)


def test_device_frames_are_drawn_per_surface() -> None:
    for surface in SURFACES:
        html = render_wireframe({**PROPS, "surface": surface})
        assert "vw-bezel" in html and f"{surface} wireframe" in html
    assert "vw-bezel" not in render_wireframe(OLD)


def test_svg_is_natural_size_and_one_cell_is_a_44px_target() -> None:
    html = render_wireframe(PROPS)
    assert re.search(r'<svg[^>]* width="\d+" height="\d+"', html)
    assert (screens.CELL_W - screens.PAD) >= 45 and (screens.CELL_H - screens.PAD) >= 45
    assert 'data-min-unit="45"' in html


def test_pins_number_notes_in_order_and_unknown_regions_are_skipped() -> None:
    html = render_wireframe(
        {**PROPS, "notes": [{"region": "Z", "text": "gone"}, *PROPS["notes"]]}
    )
    numbers = re.findall(r'<li value="(\d+)" class="vw-note"', html)
    assert numbers == ["2", "3", "4"] and "gone" not in html


def test_compare_draws_two_frames_each_with_its_own_pattern_ids() -> None:
    props = {
        **PROPS,
        "compare": {"grid": ["AA"], "regions": {"A": "a"}, "kinds": {"A": "media"}},
    }
    html = render_wireframe(props)
    assert html.count("<figure") == 2 and "Before" in html and "After" in html
    assert "vw-compare" in html
    ids = re.findall(r'<pattern id="(vw-[0-9a-f]+-\w+)"', html)
    assert len(ids) == len(set(ids)) == 4


def test_copy_text_gives_regions_and_note_text() -> None:
    lines = copy_text(PROPS).splitlines()
    assert lines[0] == "Orders <b>list</b> (browser wireframe)"
    assert "- filters [input]" in lines and "- footer" in lines
    assert "1. filters: Stays in the URL" in lines
    assert "3. order list: Retry on failure" in lines
    compared = copy_text({**PROPS, "compare": OLD}).splitlines()
    assert "Before:" in compared and "After:" in compared


def test_old_props_render_as_before_and_validate() -> None:
    assert check_props("wireframe", OLD, 1) == []
    html = render_wireframe(OLD)
    assert "vb-wire" in html and "vw-pin" not in html and "pattern" not in html
    assert "vw-notes" not in html


def test_schema_checks_surface_kinds_notes_and_compare() -> None:
    assert rules(PROPS) == []
    assert rules({**PROPS, "surface": "watch"}) == ["surface"]
    assert rules({**PROPS, "kinds": {"H": "blob"}}) == ["kind-unknown"]
    assert rules({**PROPS, "kinds": {"Z": "nav"}}) == ["kind-region"]
    assert rules({**PROPS, "notes": [{"region": "Z", "text": "x"}]}) == ["note-region"]
    assert rules({**PROPS, "notes": [{"region": "H"}]}) == ["missing-key"]
    assert rules({**PROPS, "compare": "x"}) == ["type"]
    bad = {"grid": ["AB"], "regions": {"A": "a"}}
    assert rules({**PROPS, "compare": bad}) == ["region-undeclared"]


def test_wireframe_is_registered() -> None:
    assert "wireframe" in COMPONENTS and "ui-states" in COMPONENTS


STATES: dict[str, Any] = {
    "screen": "Orders",
    "empty": {"shows": "Nothing <b>yet</b>"},
    "loading": {"na": "instant"},
    "error": {"shows": "Retry"},
}


def test_ui_states_layout_is_validated_and_marked() -> None:
    assert check_props("ui-states", STATES, 1) == []
    grid = {**STATES, "layout": "grid"}
    assert check_props("ui-states", grid, 1) == []
    assert 'data-layout="grid"' in render_ui_states(grid)
    assert "data-layout" not in render_ui_states(STATES)
    bad = check_props("ui-states", {**STATES, "layout": "wall"}, 1)
    assert [f.rule for f in bad] == ["layout"]


def test_ui_states_copy_text_lists_each_state() -> None:
    html = render_ui_states(STATES)
    assert "data-copy=" in html and "&lt;b&gt;yet&lt;/b&gt;" in html
    assert screens.ui_states_copy(STATES).splitlines() == [
        "Orders (ui-states)",
        "- empty: Nothing <b>yet</b>",
        "- loading: n/a, instant",
        "- error: Retry",
    ]


def test_static_export_shows_svg_notes_and_every_state_without_script() -> None:
    body = render_page(DOC, "t.md").body
    assert "<svg" in body and "vw-notes" in body and "<script" not in body
    assert body.count('class="vb-state ') == 3


def test_stress_fixture_escapes_hostile_text() -> None:
    text = (FIXTURES / "rich-wireframe-stress.md").read_text(encoding="utf-8")
    assert blocks.check(text) == []
    body = render_page(text, "t.md").body
    assert "vb-error" not in body and "<script>alert" not in body
    assert "<img src=x" not in body and "style=" not in body
    assert body.count('class="vw-region ') >= 20


def test_normal_fixture_is_valid() -> None:
    text = (FIXTURES / "rich-wireframe.md").read_text(encoding="utf-8")
    assert blocks.check(text) == []
    body = render_page(text, "t.md").body
    assert body.count("<figure") == 3 and 'data-layout="grid"' in body


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
    shared_page.wait_for_selector(".wireframe .vw-region[role=button]")
    shared_page.wait_for_timeout(600)  # the live refresh rebuilds widgets once
    shared_page.wait_for_selector(".wireframe .vw-region[role=button]")
    yield shared_page
    assert problems == []
    shared_page.goto("about:blank")
    server.shutdown()
    server.server_close()
    thread.join(5)


def region(page: Any, letter: str) -> Any:
    return page.locator(f'.wireframe .vw-region[data-region="{letter}"]')


def view_box(page: Any) -> list[float]:
    raw = page.locator(".wireframe .vw-view svg").get_attribute("viewBox")
    return [float(v) for v in (raw or "").split()]


def pinch(page: Any, centre: tuple[float, float], start: float, end: float) -> None:
    """Two touch points move apart (or together) around `centre` through CDP."""
    cdp = page.context.new_cdp_session(page)
    cx, cy = centre

    def points(gap: float) -> list[dict[str, float]]:
        return [{"x": cx - gap, "y": cy, "id": 1}, {"x": cx + gap, "y": cy, "id": 2}]

    cdp.send(
        "Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": points(start)}
    )
    for step in range(1, 6):
        gap = start + (end - start) * step / 5
        cdp.send(
            "Input.dispatchTouchEvent",
            {"type": "touchMove", "touchPoints": points(gap)},
        )
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


@pytest.mark.slow
def test_interact_pan_and_zoom_by_buttons_and_keys(open_page: Any) -> None:
    page = open_page
    assert page.locator(".wireframe .vb-controls").count() == 1
    home = view_box(page)
    page.get_by_role("button", name="Zoom in").click()
    assert view_box(page)[2] < home[2]
    page.get_by_role("button", name="Fit whole wireframe").click()
    assert view_box(page) == home
    page.locator(".wireframe .vw-view").focus()
    page.keyboard.press("+")
    zoomed = view_box(page)
    assert zoomed[2] < home[2]
    page.keyboard.press("ArrowRight")
    assert view_box(page)[0] != zoomed[0]
    page.keyboard.press("0")
    assert view_box(page) == home


@pytest.mark.slow
def test_interact_ctrl_wheel_zooms_and_plain_wheel_does_not(open_page: Any) -> None:
    page = open_page
    home = view_box(page)
    box = page.locator(".wireframe .vw-view svg").bounding_box()
    page.mouse.move(box["x"] + 60, box["y"] + 60)
    page.mouse.wheel(0, 120)
    assert view_box(page) == home
    page.locator(".wireframe .vw-view svg").evaluate(
        "(el, at) => el.dispatchEvent(new WheelEvent('wheel', {deltaY: -120,"
        " ctrlKey: true, clientX: at[0], clientY: at[1], bubbles: true,"
        " cancelable: true}))",
        [box["x"] + 60, box["y"] + 60],
    )
    assert view_box(page)[2] < home[2]


@pytest.mark.slow
def test_interact_pinch_zooms_and_double_tap_fits(open_page: Any) -> None:
    page = open_page
    home = view_box(page)
    box = page.locator(".wireframe .vw-view svg").bounding_box()
    centre = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pinch(page, centre, 20, 90)
    assert view_box(page)[2] < home[2]
    page.touchscreen.tap(centre[0], box["y"] + 4)
    page.touchscreen.tap(centre[0], box["y"] + 4)
    page.wait_for_timeout(100)
    assert view_box(page) == home


@pytest.mark.slow
def test_interact_select_region_announces_its_notes(open_page: Any) -> None:
    page = open_page
    region(page, "L").click()
    assert region(page, "L").get_attribute("aria-pressed") == "true"
    assert page.locator(".wireframe .vw-region.vw-sel").count() == 1
    text = page.locator(".vw-detail").inner_text()
    assert "order list" in text and "Note 2" in text and "Loads 50 at a time" in text
    assert page.locator(".vw-detail").get_attribute("aria-live") == "polite"
    assert page.locator(".vw-note.vw-note-on").count() == 1
    region(page, "H").focus()
    page.keyboard.press("Enter")
    assert "No notes" in page.locator(".vw-detail").inner_text()
    page.keyboard.press("Escape")
    assert region(page, "H").get_attribute("aria-pressed") == "false"


@pytest.mark.slow
def test_interact_arrow_keys_move_between_regions(open_page: Any) -> None:
    page = open_page
    region(page, "H").focus()
    page.keyboard.press("ArrowRight")
    assert page.evaluate("document.activeElement.dataset.region") == "S"
    page.keyboard.press("End")
    assert page.evaluate("document.activeElement.dataset.region") == "L"
    page.keyboard.press("ArrowLeft")
    assert page.evaluate("document.activeElement.dataset.region") == "S"


@pytest.mark.slow
def test_interact_regions_are_44px_targets_at_first_paint(open_page: Any) -> None:
    page = open_page
    page.set_viewport_size({"width": 320, "height": 800})
    page.reload()
    page.wait_for_selector(".wireframe .vw-region[role=button]")
    page.wait_for_timeout(600)
    small = page.evaluate(
        "[...document.querySelectorAll('.wireframe .vw-box')]"
        ".map(r => r.getBoundingClientRect())"
        ".filter(b => b.width < 44 || b.height < 44).length"
    )
    assert small == 0
    sizes = page.evaluate(
        "() => [document.documentElement.scrollWidth,"
        " document.documentElement.clientWidth]"
    )
    assert sizes[0] <= sizes[1]
    page.set_viewport_size({"width": 900, "height": 700})


@pytest.mark.slow
def test_interact_state_tabs_move_by_arrow_keys(open_page: Any) -> None:
    page = open_page
    assert page.get_by_role("tablist").count() == 1
    tab = page.get_by_role("tab", name="empty")
    tab.focus()
    page.keyboard.press("ArrowRight")
    assert "Skeleton" in page.locator(".vb-state:visible").inner_text()
    page.keyboard.press("End")
    assert "Retry" in page.locator(".vb-state:visible").inner_text()
    page.keyboard.press("Home")
    assert "Nothing yet" in page.locator(".vb-state:visible").inner_text()
    panel = page.get_by_role("tabpanel")
    assert panel.get_attribute("aria-labelledby")
