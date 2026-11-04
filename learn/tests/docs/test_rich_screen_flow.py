"""The screen-flow component: layout of lanes and ranks, faults, text alternative,
escaping and interactions (pan and zoom, focus order, notes panel, 44px targets)."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import check, check_props
from varde_learn.docs.pages.blocks.screen_flow import MAX_SCREENS, MAX_STEPS
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.blocks_render.screen_flow import (
    alternative_lines,
    copy_text,
    render_screen_flow,
)
from varde_learn.docs.pages.blocks_render.screen_flow_layout import (
    Screen,
    plan_flow,
)
from varde_learn.docs.pages.render import render_page
from varde_learn.docs.pages.serve import PageServer

F1 = "#blk-f1"  # the fixture also holds a one-screen flow, f2
FIXTURES = Path(__file__).parent / "fixtures" / "widgets"
STATIC = Path(str(files("varde_learn.docs.pages").joinpath("static")))


def screen(ident: str, title: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "id": ident,
        "title": title or ident.upper(),
        "grid": ["HH", "BB"],
        "regions": {"H": "header", "B": "body"},
        **extra,
    }


def sample(**extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "desc": "d",
        "screens": [
            screen("a", "Alpha", notes=[{"region": "B", "text": "A note"}]),
            screen("b", "Beta"),
            screen("c", "Gamma"),
        ],
        "steps": [
            {"from": "a", "to": "b", "label": "go"},
            {"from": "b", "to": "c"},
        ],
    }
    return {**data, **extra}


def rules(data: dict[str, Any]) -> list[str]:
    return [e.rule for e in check_props("screen-flow", data, 1)]


def two_lanes() -> dict[str, Any]:
    return sample(
        screens=[*sample()["screens"], screen("x", "Xray"), screen("y", "Yankee")],
        steps=[
            {"from": "a", "to": "b", "label": "go"},
            {"from": "b", "to": "c"},
            {"from": "x", "to": "y", "label": "next"},
        ],
        lanes=[
            {"title": "Web", "screens": ["a", "b", "c"]},
            {"title": "Phone", "screens": ["x", "y"]},
        ],
    )


def test_layout_puts_ranks_in_columns_and_lanes_in_rows() -> None:
    placed = [Screen(i, (60, 40), lane) for i, lane in (("a", 0), ("b", 0), ("x", 1))]
    steps = [("a", "b", "go")]
    plan = plan_flow(placed, steps, ["Web", "Phone"], "LR")
    boxes = {t.id: t.box for t in plan.tiles}
    assert boxes["a"].x < boxes["b"].x and boxes["a"].y == boxes["b"].y
    assert boxes["x"].y > boxes["a"].y and boxes["x"].x == boxes["a"].x
    assert [t.id for t in plan.tiles] == ["a", "b", "x"]  # lane by lane
    link = plan.links[0]
    (x1, y1), (x2, y2) = link.points
    assert y1 == y2 and x1 == boxes["a"].x + boxes["a"].w and x2 == boxes["b"].x
    assert link.label is not None and link.label.y + link.label.h <= y1
    assert len(plan.bands) == 2


def test_layout_down_swaps_the_axes() -> None:
    placed = [Screen(i, (60, 40), lane) for i, lane in (("a", 0), ("b", 0), ("x", 1))]
    plan = plan_flow(placed, [("a", "b", "go")], ["Web", "Phone"], "TB")
    boxes = {t.id: t.box for t in plan.tiles}
    assert boxes["a"].y < boxes["b"].y and boxes["a"].x == boxes["b"].x
    assert boxes["x"].x > boxes["a"].x and boxes["x"].y == boxes["a"].y
    (x1, y1), (x2, y2) = plan.links[0].points
    assert x1 == x2 and y1 == boxes["a"].y + boxes["a"].h and y2 == boxes["b"].y


def test_tiles_never_overlap_and_stay_inside_the_plan() -> None:
    placed = [Screen(f"s{i}", (30 + 9 * i, 40 + 5 * i), i % 3) for i in range(9)]
    steps = [(f"s{i}", f"s{i + 3}", "") for i in range(6)]
    for direction in ("LR", "TB"):
        plan = plan_flow(placed, steps, ["1", "2", "3"], direction)
        boxes = [t.box for t in plan.tiles]
        for n, box in enumerate(boxes):
            assert box.x >= 0 and box.x + box.w <= plan.width
            assert box.y >= 0 and box.y + box.h <= plan.height
            assert not any(box.overlaps(other) for other in boxes[n + 1 :])


def test_labels_sit_in_open_space() -> None:
    plan, _ = (
        plan_flow(
            [Screen("a", (60, 40), 0), Screen("b", (60, 40), 0)],
            [("a", "b", "an extremely long label that must wrap and then be cut off")],
            [""],
            "LR",
        ),
        None,
    )
    link = plan.links[0]
    assert link.label is not None and 1 < len(link.lines) <= 3
    assert link.lines[-1].endswith("…")
    tiles = [t.box for t in plan.tiles]
    assert not any(link.label.overlaps(t) for t in tiles)


def test_valid_sample_and_defaults() -> None:
    assert rules(sample()) == [] and rules(two_lanes()) == []
    assert rules({"screens": [screen("a")]}) == []  # no steps, no lanes, no desc


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ({"steps": [{"from": "a", "to": "c"}]}, "cell-taken"),
        (
            {
                "steps": [
                    {"from": "a", "to": "b"},
                    {"from": "b", "to": "c"},
                    {"from": "a", "to": "c"},
                ]
            },
            "step-rank",
        ),
        ({"steps": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]}, "cycle"),
        ({"steps": [{"from": "a", "to": "a"}]}, "cycle"),
        ({"steps": [{"from": "a", "to": "zz"}]}, "step-screen"),
        ({"steps": [{"from": "zz", "to": "a"}]}, "step-screen"),
        (
            {"steps": [{"from": "a", "to": "b"}, {"from": "a", "to": "b"}]},
            "step-duplicate",
        ),
        ({"screens": [screen("a"), screen("a")], "steps": []}, "screen-duplicate"),
        ({"steps": []}, "type"),
        ({"extra": 1}, "unknown-key"),
        ({"screens": [{"id": "a", "title": "A"}]}, "missing-key"),
        ({"screens": [screen("a", surface="watch")], "steps": []}, "surface"),
        (
            {
                "screens": [screen("a", notes=[{"region": "Z", "text": "x"}])],
                "steps": [],
            },
            "note-region",
        ),
        ({"steps": [{"from": "a", "to": "b", "x": 1}]}, "unknown-key"),
    ],
)
def test_spec_faults(change: dict[str, Any], rule: str) -> None:
    assert rule in rules(sample(**change))


def test_a_step_across_lanes_is_a_fault_with_advice() -> None:
    data = two_lanes()
    data["steps"] = [*data["steps"], {"from": "x", "to": "b"}]
    errors = check_props("screen-flow", data, 1)
    assert [e.rule for e in errors] == ["step-lane"]
    assert "crosses lanes" in errors[0].message


def test_a_skipped_rank_message_asks_for_an_intermediate_screen() -> None:
    chain = sample(
        steps=[
            {"from": "a", "to": "b"},
            {"from": "b", "to": "c"},
            {"from": "a", "to": "c"},
        ]
    )
    errors = check_props("screen-flow", chain, 1)
    assert [e.rule for e in errors] == ["step-rank"]
    assert "intermediate screen" in errors[0].message


def test_two_screens_in_one_lane_and_rank_are_a_fault() -> None:
    data = sample(steps=[{"from": "a", "to": "b"}, {"from": "a", "to": "c"}])
    assert "cell-taken" in rules(data)


@pytest.mark.parametrize(
    ("lanes", "rule"),
    [
        ([{"title": "T", "screens": ["a", "b"]}], "lane-missing"),
        (
            [
                {"title": "T", "screens": ["a", "b", "c"]},
                {"title": "U", "screens": ["a"]},
            ],
            "lane-duplicate",
        ),
        ([{"title": "T", "screens": ["a", "b", "c", "zz"]}], "lane-screen"),
        ([{"title": "T"}], "missing-key"),
        ([{"title": "T", "screens": []}], "type"),
    ],
)
def test_lane_faults(lanes: list[Any], rule: str) -> None:
    assert rule in rules(sample(lanes=lanes))


def test_limits_are_faults() -> None:
    many = [screen(f"s{i}") for i in range(MAX_SCREENS + 1)]
    assert "too-many" in rules({"screens": many})
    chain = [screen(f"s{i}") for i in range(MAX_STEPS + 2)]
    steps = [{"from": f"s{i}", "to": f"s{i + 1}"} for i in range(MAX_STEPS + 1)]
    assert rules({"screens": chain, "steps": steps}).count("too-many") == 2
    ok = [screen(f"s{i}") for i in range(MAX_SCREENS)]
    ok_steps = [{"from": f"s{i}", "to": f"s{i + 1}"} for i in range(MAX_SCREENS - 1)]
    assert rules({"screens": ok, "steps": ok_steps}) == []


def test_render_draws_both_directions_with_unique_ids_and_no_script() -> None:
    data = two_lanes()
    data["screens"][0]["kinds"] = {"H": "nav", "B": "list"}
    data["screens"][3]["kinds"] = {"B": "list"}
    html = render_screen_flow(data)
    assert 'class="vb screen-flow vd-sf"' in html and "data-copy=" in html
    assert html.count('class="vd-sf-view vd-sf-') == 2
    assert html.count('class="vd-sf-screen"') == 10  # 5 screens, drawn twice
    assert html.count('class="vd-sf-band"') == 4
    ids = re.findall(r'<pattern id="(vw-[0-9a-z]+-\w+)"', html)
    assert len(ids) == 6 and len(ids) == len(set(ids))
    assert "style=" not in html and "<script" not in html
    assert html.count('class="vd-sf-head"') == 6  # 3 steps, drawn twice
    assert html.count('role="region" tabindex="0"') == 2


def test_hatch_patterns_come_from_the_wireframe_frame() -> None:
    kinds = {"B": "list", "H": "nav"}
    data = sample(screens=[screen("a", kinds=kinds), screen("b"), screen("c")])
    html = render_screen_flow(data)
    assert 'class="vw-hatch"' in html and "[list]" in html


def test_alternative_list_equals_the_steps() -> None:
    data = two_lanes()
    lines = alternative_lines(data)
    assert lines == [
        "Alpha (Web lane): 2 regions: header, body; next: Beta (go)",
        "Beta (Web lane): 2 regions: header, body; next: Gamma",
        "Gamma (Web lane): 2 regions: header, body; end of flow",
        "Xray (Phone lane): 2 regions: header, body; next: Yankee (next)",
        "Yankee (Phone lane): 2 regions: header, body; end of flow",
    ]
    html = render_screen_flow(data)
    plain = re.sub(r'<ol class="vd-sf-notes".*?</ol>', "", html, flags=re.DOTALL)
    items = re.findall(r'<li class="vd-sf-item".*?</li>', plain, re.DOTALL)
    assert len(items) == 5
    for item, line in zip(items, lines, strict=True):
        assert re.sub(r"<[^>]+>", "", item) == line
    assert 'class="vd-sf-notes"' in html and "A note" in html


def test_copy_text_numbers_the_same_lines() -> None:
    lines = copy_text(sample()).splitlines()
    assert lines[0] == "Screen flow (screen flow, 3 screens, 2 steps)"
    assert lines[1:] == [
        f"{n}. {t}" for n, t in enumerate(alternative_lines(sample()), 1)
    ]


def test_default_single_lane_has_no_band_and_no_lane_text() -> None:
    html = render_screen_flow(sample())
    assert "vd-sf-band" not in html and "lane)" not in html


def test_hostile_text_is_escaped_everywhere() -> None:
    bad = '<script>alert(1)</script> "><img src=x onerror=alert(2)> javascript:x'
    data = sample(
        title=bad,
        desc=bad,
        screens=[screen("a", bad, notes=[{"region": "B", "text": bad}]), screen("b")],
        steps=[{"from": "a", "to": "b", "label": bad}],
        lanes=[{"title": bad, "screens": ["a", "b"]}],
    )
    html = render_screen_flow(data)
    assert "<script>alert" not in html and "<img src=x" not in html
    assert "&lt;script&gt;" in html
    assert '"><img' not in html
    attr = re.search(r'data-copy="([^"]*)"', html)
    assert attr and "<" not in attr.group(1)


def test_registered_and_fixtures_render_through_the_page() -> None:
    assert "screen-flow" in COMPONENTS
    for name, floor in (("rich-screen-flow", 2), ("rich-screen-flow-stress", 1)):
        doc = (FIXTURES / f"{name}.md").read_text()
        assert check(doc) == []
        body = render_page(doc, "t.md").body
        assert body.count('class="vb screen-flow vd-sf"') == floor
        assert "<img" not in body and "<script>alert" not in body
        assert "style=" not in body and "vb-error" not in body


def test_stress_fixture_has_twelve_screens_and_hostile_text_escaped() -> None:
    body = render_page(
        (FIXTURES / "rich-screen-flow-stress.md").read_text(), "t.md"
    ).body
    assert body.count('class="vd-sf-screen"') == 24
    assert "&lt;script&gt;" in body


def test_invalid_props_render_an_error_card() -> None:
    doc = "```ui id=bad\nbad = screen-flow(screens: [])\n```\n"
    body = render_page(doc, "t.md").body
    assert "vb-error" in body and "screen-flow block has" in body


def test_css_print_block_is_last_and_uses_tokens_only() -> None:
    css = (STATIC / "css" / "58-screen-flow.css").read_text()
    assert css.rstrip().rsplit("@media", 1)[1].startswith(" print")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css)
    assert "forced-colors" in css and "max-width: 30rem" in css
    assert "overflow-wrap: anywhere" not in css


def test_js_uses_no_banned_sink_and_no_foreign_class() -> None:
    js = (STATIC / "screen_flow.js").read_text()
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|eval\(|\.style\.", js)
    owned = set(re.findall(r"vd-sf-[a-z-]+", js))
    assert owned and not set(re.findall(r"\bvw-[a-z-]+", js))
    for other in ("wireframe.js", "flow.js", "tabs.js", "viewport.js"):
        text = (STATIC / other).read_text()
        assert not owned & set(re.findall(r"vd-sf-[a-z-]+", text))


@pytest.fixture(scope="module")
def shared_page(browser_session: Any) -> Any:
    page = browser_session.new_page(
        viewport={"width": 1100, "height": 800}, has_touch=True
    )
    page.set_default_timeout(10_000)
    return page


@pytest.fixture
def open_page(tmp_path: Path, shared_page: Any) -> Iterator[Any]:
    doc = tmp_path / "plan.md"
    doc.write_text((FIXTURES / "rich-screen-flow.md").read_text(), encoding="utf-8")
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    problems: list[str] = []
    shared_page.on("pageerror", lambda error: problems.append(str(error)))
    shared_page.goto(f"http://127.0.0.1:{server.port}/")
    shared_page.wait_for_selector(".screen-flow .vd-sf-screen[role=button]")
    shared_page.wait_for_timeout(600)  # the live refresh rebuilds widgets once
    shared_page.wait_for_selector(".screen-flow .vd-sf-screen[role=button]")
    yield shared_page
    assert problems == []
    shared_page.goto("about:blank")
    server.shutdown()
    server.server_close()
    thread.join(5)


def tile(page: Any, ident: str) -> Any:
    return page.locator(f'.vd-sf-across .vd-sf-screen[data-screen="{ident}"]').first


def view_box(page: Any) -> list[float]:
    raw = page.locator(".vd-sf-across svg.vd-sf-svg").first.get_attribute("viewBox")
    return [float(v) for v in (raw or "").split()]


@pytest.mark.slow
def test_interact_pan_and_zoom_by_buttons_and_keys(open_page: Any) -> None:
    page = open_page
    home = view_box(page)
    page.get_by_role("button", name="Zoom in").first.click()
    assert view_box(page)[2] < home[2]
    page.get_by_role("button", name="Zoom out").first.click()
    page.get_by_role("button", name="Zoom out").first.click()
    assert view_box(page)[2] > home[2]
    page.locator(F1).get_by_role("button", name="Fit whole flow").click()
    assert view_box(page) == home
    page.locator(".vd-sf-across.vd-sf-view").first.focus()
    page.keyboard.press("+")
    assert view_box(page)[2] < home[2]
    page.keyboard.press("0")
    assert view_box(page) == home


@pytest.mark.slow
def test_interact_focus_order_follows_the_steps(open_page: Any) -> None:
    page = open_page
    tile(page, "cart").focus()
    order = ["cart"]
    for _ in range(4):
        page.keyboard.press("ArrowRight")
        order.append(page.evaluate("document.activeElement.dataset.screen"))
    assert order == ["cart", "pay", "done", "inbox", "receipt"]
    page.keyboard.press("Home")
    assert page.evaluate("document.activeElement.dataset.screen") == "cart"
    page.keyboard.press("End")
    assert page.evaluate("document.activeElement.dataset.screen") == "receipt"
    assert page.locator(f"{F1} .vd-sf-across .vd-sf-screen[tabindex='0']").count() == 1


@pytest.mark.slow
def test_interact_select_screen_announces_its_notes(open_page: Any) -> None:
    page = open_page
    tile(page, "cart").click()
    assert tile(page, "cart").get_attribute("aria-pressed") == "true"
    text = page.locator(f"{F1} .vd-sf-detail").inner_text()
    assert "Cart" in text and "Note 1" in text and "Disabled while" in text
    assert "next: Payment (Pay)" in text
    assert page.locator(f"{F1} .vd-sf-detail").get_attribute("aria-live") == "polite"
    assert page.locator(f"{F1} .vd-sf-item-on").count() == 1
    tile(page, "done").focus()
    page.keyboard.press("Enter")
    assert "No notes" in page.locator(f"{F1} .vd-sf-detail").inner_text()
    page.keyboard.press("Escape")
    assert tile(page, "done").get_attribute("aria-pressed") == "false"


@pytest.mark.slow
def test_interact_screens_are_44px_targets_in_both_layouts(open_page: Any) -> None:
    page = open_page
    for width in (1100, 320):
        page.set_viewport_size({"width": width, "height": 800})
        page.wait_for_timeout(100)
        small = page.evaluate(
            "[...document.querySelectorAll('#blk-f1 .vd-sf-screen')]"
            ".map(r => r.getBoundingClientRect())"
            ".filter(b => b.width > 0 && (b.width < 44 || b.height < 44)).length"
        )
        assert small == 0
        shown = page.evaluate(
            "[...document.querySelectorAll('#blk-f1 .vd-sf-screen')]"
            ".filter(r => r.getBoundingClientRect().width > 0).length"
        )
        assert shown == 5
        sizes = page.evaluate(
            "() => [document.documentElement.scrollWidth,"
            " document.documentElement.clientWidth]"
        )
        assert sizes[0] <= sizes[1]
    page.set_viewport_size({"width": 1100, "height": 800})
