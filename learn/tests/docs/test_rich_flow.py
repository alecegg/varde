"""The flow component: server SVG, text alternative, Copy text, interactions."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import check_props
from varde_learn.docs.pages.blocks_render.flow import copy_text, render_flow
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.render import render_page
from varde_learn.docs.pages.serve import PageServer

STEPS = [
    {"id": "cart", "text": "Review cart", "next": ["pay"]},
    {"id": "pay", "text": "Pay <b>now</b>", "next": ["done", "failed"]},
    {"id": "done", "text": "Show receipt"},
    {"id": "failed", "text": "Show error " + "long " * 12, "next": ["pay"]},
]
PROPS: dict[str, Any] = {"title": "Checkout", "step": STEPS}
FIXTURES = Path(__file__).parent / "fixtures" / "widgets"
DOC = """# Flow

```ui id=flow
flow = flow(
  title: "Checkout",
  step: [
    {"id": "cart", "text": "Review cart", "next": ["pay"]},
    {"id": "pay", "text": "Pay", "next": ["done", "failed"]},
    {"id": "done", "text": "Receipt"},
    {"id": "failed", "text": "Error", "next": ["pay"]},
  ],
)
```
"""


def node_tops(html: str) -> dict[str, float]:
    """The y of each node's translate(x y) in the first svg."""
    found = re.findall(
        r'data-id="([^"]+)" transform="translate\(([\d.]+) ([\d.]+)\)"',
        html,
    )
    return {name: float(y) for name, _, y in found}


def test_server_html_holds_the_svg_the_list_and_the_copy_text() -> None:
    html = render_flow(PROPS)
    assert "<svg" in html and 'class="vb flow"' in html
    assert '<ol class="vb-flow">' in html and 'class="vb-step-id"' in html
    assert 'vb-branch"' in html and "data-copy=" in html
    assert "<b>now</b>" not in html and "&lt;b&gt;now&lt;/b&gt;" in html
    assert "style=" not in html and "<script" not in html


def test_layout_puts_each_step_below_what_it_follows() -> None:
    top = node_tops(render_flow(PROPS))
    assert top["cart"] < top["pay"] < top["done"]
    assert top["pay"] < top["failed"]


def test_long_titles_wrap_into_several_lines() -> None:
    html = render_flow(PROPS)
    node = re.search(r'data-id="failed".*?</g>', html, re.DOTALL)
    assert node is not None and node.group(0).count("<tspan") > 2


def test_copy_text_lists_the_steps_in_order() -> None:
    lines = copy_text(PROPS).splitlines()
    assert lines[0] == "Checkout (flow of 4 steps)"
    assert lines[1] == "1. cart: Review cart -> pay"
    assert lines[2].endswith("-> done, failed")
    assert lines[3] == "3. done: Show receipt"


def test_flow_is_registered_and_keeps_its_props() -> None:
    assert "flow" in COMPONENTS
    assert check_props("flow", PROPS, 1) == []


def test_static_export_shows_the_diagram_without_script() -> None:
    body = render_page(DOC, "t.md").body
    assert "<svg" in body and "vd-view" in body


def test_stress_fixture_escapes_hostile_text_and_lays_out_forty_steps() -> None:
    text = (FIXTURES / "rich-flow-stress.md").read_text(encoding="utf-8")
    body = render_page(text, "t.md").body
    assert "vb-error" not in body and "<script>alert" not in body
    assert body.count('class="vd-node') >= 41


def test_a_next_to_an_unknown_step_does_not_break_rendering() -> None:
    html = render_flow({"step": [{"id": "a", "text": "A", "next": ["zzz"]}]})
    assert "vd-node" in html and "vd-edge" not in html


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
    shared_page.wait_for_selector(".flow .vd-node[role=button]")
    shared_page.wait_for_timeout(600)  # the live refresh rebuilds widgets once
    shared_page.wait_for_selector(".flow .vd-node[role=button]")
    yield shared_page
    assert problems == []
    shared_page.goto("about:blank")
    server.shutdown()
    server.server_close()
    thread.join(5)


def step(page: Any, ident: str) -> Any:
    return page.locator(f'.flow .vd-node[data-id="{ident}"]')


def view_box(page: Any) -> list[float]:
    raw = page.locator(".flow .vd-view svg").get_attribute("viewBox")
    return [float(v) for v in (raw or "").split()]


@pytest.mark.slow
def test_interact_select_highlights_dependencies_and_reads_them_out(
    open_page: Any,
) -> None:
    page = open_page
    step(page, "pay").click()
    assert page.locator(".flow .vd-node.vd-sel").count() == 1
    assert page.locator(".flow .vd-node.vf-up").count() == 2  # cart, failed (cycle)
    assert (
        page.locator(".flow .vd-node.vf-down").count() == 1
    )  # done; failed is shown as before
    text = page.locator(".flow .vd-detail").inner_text()
    assert "Before it" in text and "After it" in text and "Review cart" in text
    assert step(page, "pay").get_attribute("aria-pressed") == "true"
    step(page, "pay").click()
    page.mouse.move(0, 0)
    assert step(page, "pay").get_attribute("aria-pressed") == "false"


@pytest.mark.slow
def test_interact_pan_zoom_and_fit(open_page: Any) -> None:
    page = open_page
    assert page.locator(".flow .vb-controls").count() == 1
    home = view_box(page)
    page.get_by_role("button", name="Zoom in").click()
    assert view_box(page)[2] < home[2]
    page.get_by_role("button", name="Fit whole flow").click()
    assert view_box(page) == home
    page.locator(".flow .vd-view").focus()
    page.keyboard.press("+")
    assert view_box(page)[2] < home[2]
    page.keyboard.press("0")
    assert view_box(page) == home


@pytest.mark.slow
def test_interact_arrow_keys_follow_edges_and_enter_selects(open_page: Any) -> None:
    page = open_page
    step(page, "cart").focus()
    page.keyboard.press("ArrowDown")
    assert page.evaluate("document.activeElement.dataset.id") == "pay"
    page.keyboard.press("ArrowDown")
    assert page.evaluate("document.activeElement.dataset.id") == "done"
    page.keyboard.press("ArrowUp")
    assert page.evaluate("document.activeElement.dataset.id") == "pay"
    page.keyboard.press("Enter")
    assert page.locator(".flow .vd-node.vd-sel").count() == 1
    page.keyboard.press("Escape")
    assert step(page, "pay").get_attribute("aria-pressed") == "false"


@pytest.mark.slow
def test_interact_flow_fits_the_width_on_first_paint(
    open_page: Any,
) -> None:
    page = open_page
    page.set_viewport_size({"width": 320, "height": 800})
    page.reload()
    page.wait_for_selector(".flow .vd-node[role=button]")
    page.wait_for_timeout(600)
    widths = page.evaluate(
        "() => { const v = document.querySelector('.flow .vd-view');"
        " return [v.querySelector('svg').getBoundingClientRect().width,"
        " v.clientWidth]; }"
    )
    assert widths[0] <= widths[1]  # the whole flow is inside the view
    sizes = page.evaluate(
        "() => [document.documentElement.scrollWidth,"
        " document.documentElement.clientWidth]"
    )
    assert sizes[0] <= sizes[1]
    page.set_viewport_size({"width": 900, "height": 700})
