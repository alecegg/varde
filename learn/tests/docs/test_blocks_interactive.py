"""Interactive widgets for typed blocks: served script, hooks, Chromium behavior."""

from __future__ import annotations

import http.client
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.render import render_page
from varde_learn.docs.pages.serve import PageServer

DOC = """# Plan

```ui id=opts
opts = table(
  caption: "Options",
  columns: ["option", "cost"],
  rows: [["queue", "30"], ["cache", "5"], ["batch", "100"], ["stream", "7"]],
)
```

```ui id=states
states = ui-states(
  screen: "Orders",
  empty: {"shows": "Nothing yet"},
  loading: {"shows": "Skeleton rows"},
  error: {"shows": "Retry"},
)
```

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

```ui id=lat
lat = chart(
  kind: "bar",
  title: "Latency",
  unit: "ms",
  labels: ["before", "after"],
  series: [{"name": "p50", "values": [120, 80]}],
)
```

```ui id=model
model = data-model(
  entity: [
    {"name": "customer", "key": "id", "fields": {"id": "uuid"}},
    {
      "name": "order",
      "key": "id",
      "fields": {"id": "uuid", "customer_id": "uuid"},
      "relations": [{"to": "customer", "kind": "many-to-one"}]
    },
  ],
)
```
"""


class Running:
    def __init__(self, server: PageServer) -> None:
        self.server = server
        self.host = f"127.0.0.1:{server.port}"

    def get(self, path: str) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        conn.request("GET", path, headers={"Host": self.host})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, dict(response.getheaders()), data


@pytest.fixture
def running(tmp_path: Path) -> Iterator[Running]:
    doc = tmp_path / "plan.md"
    doc.write_text(DOC, encoding="utf-8")
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield Running(server)
    server.shutdown()
    server.server_close()
    thread.join(5)


def test_blocks_script_served_with_parent_csp(running: Running) -> None:
    status, headers, body = running.get("/static/blocks.js")
    assert status == 200
    assert headers["Content-Type"].startswith("text/javascript")
    csp = headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert body


def test_shell_has_script_tag_and_no_inline_script(running: Running) -> None:
    _, _, body = running.get("/")
    text = body.decode()
    assert '<script src="/static/blocks.js" defer></script>' in text
    assert '<script src="/static/recap.js" defer></script>' in text
    assert len(re.findall(r"<script\b", text)) == 4
    assert not re.search(r"<script\b(?![^>]*\bsrc=)", text)
    assert not re.search(r"\son[a-z]+=", text) and " style=" not in text


def test_script_uses_no_eval_network_or_html_injection(running: Running) -> None:
    source = running.get("/static/blocks.js")[2].decode()
    for banned in (
        "eval(",
        "new Function",
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "setAttribute('on",
    ):
        assert banned not in source, banned


def test_rendered_html_carries_widget_hooks() -> None:
    body = render_page(DOC, "t.md").body
    assert 'class="vb-table"' in body and "<thead>" in body and "<tbody>" in body
    assert body.count('class="vb-state ') == 3 and "<h5>" in body
    assert '<ol class="vb-flow">' in body and 'class="vb-step-id"' in body
    assert 'class="vb-next"' in body
    assert 'class="vb-bar ' in body and 'aria-label="p50 / before / 120 ms"' in body
    assert 'class="vb-relations"' in body


# ---- Chromium (slow tier) ---------------------------------------------------

VIEWPORT = {"width": 390, "height": 844}


@pytest.fixture(scope="module")
def shared_page(browser_session: Any) -> Any:
    page = browser_session.new_page(viewport=VIEWPORT)
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

    def note(error: Any) -> None:
        problems.append(str(error))

    shared_page.on("pageerror", note)
    shared_page.goto(f"http://127.0.0.1:{server.port}/")
    shared_page.wait_for_selector(".flow .vd-node")
    shared_page.wait_for_timeout(
        600
    )  # let the SSE open-refresh finish; it rebuilds widgets
    shared_page.wait_for_selector(".flow .vd-node")
    shared_page.doc = doc  # type: ignore[attr-defined]
    yield shared_page
    assert problems == []
    shared_page.goto("about:blank")
    shared_page.remove_listener("pageerror", note)
    server.shutdown()
    server.server_close()
    thread.join(5)


def first_column(page: Any) -> list[str]:
    return (
        page.locator(".vb-table")
        .first.locator("tbody tr:visible td:first-child")
        .all_text_contents()
    )


@pytest.mark.slow
def test_table_sorts_and_filters(open_page: Any) -> None:
    page = open_page
    sort = page.locator(".vb-table").first.locator("th .vb-sort").nth(1)
    sort.click()
    assert first_column(page) == ["cache", "stream", "queue", "batch"]
    sort.click()
    assert first_column(page) == ["batch", "queue", "stream", "cache"]
    sort.click()
    assert first_column(page) == ["queue", "cache", "batch", "stream"]
    page.locator(".vb-filter").first.fill("ca")
    assert first_column(page) == ["cache"]
    page.locator(".vb-filter").first.fill("")
    assert len(first_column(page)) == 4
    toggle = page.locator(".vb-toggle")
    toggle.click()
    assert not page.locator(".vb-relations").is_visible()
    toggle.click()
    assert page.locator(".vb-relations").is_visible()


@pytest.mark.slow
def test_ui_states_show_one_tile_at_a_time(open_page: Any) -> None:
    page = open_page
    assert page.locator(".vb-state:visible").count() == 1
    page.get_by_role("tab", name="error").click()
    visible = page.locator(".vb-state:visible")
    assert visible.count() == 1 and "Retry" in visible.inner_text()
    page.get_by_role("tab", name="error").press("ArrowRight")
    assert "Nothing yet" in page.locator(".vb-state:visible").inner_text()


@pytest.mark.slow
def test_flow_pans_zooms_and_highlights(open_page: Any) -> None:
    page = open_page
    svg = page.locator(".flow .vd-view svg")
    start = svg.get_attribute("viewBox")
    page.get_by_role("button", name="Zoom in").click()
    zoomed = svg.get_attribute("viewBox")
    assert zoomed != start
    page.get_by_role("button", name="Fit whole flow").click()
    assert svg.get_attribute("viewBox") == start
    page.locator(".flow .vd-node", has_text="Pay").click()
    assert page.locator(".flow .vd-node.vd-sel").count() == 1
    assert page.locator(".flow .vd-node.vf-up").count() == 2  # cart and failed (cycle)
    assert (
        page.locator(".flow .vd-node.vf-down").count() == 1
    )  # done; failed is shown as before
    page.locator(".flow .vd-node", has_text="Pay").click()
    page.mouse.move(0, 0)
    assert page.locator(".flow .vd-node[aria-pressed=true]").count() == 0


@pytest.mark.slow
def test_chart_hover_reads_value(open_page: Any) -> None:
    page = open_page
    page.locator(".vb-bar").first.hover()
    assert "120" in page.locator(".vb-readout").inner_text()
    page.locator(".vb-bar").nth(1).click()
    assert "80" in page.locator(".vb-readout").inner_text()


@pytest.mark.slow
def test_no_horizontal_scroll_at_390(open_page: Any) -> None:
    page = open_page
    sizes = page.evaluate(
        "() => [document.documentElement.scrollWidth,"
        " document.documentElement.clientWidth]"
    )
    assert sizes[0] <= sizes[1] == 390
    small = page.evaluate(
        "() => Array.from(document.querySelectorAll('.vb button, .vb input'))"
        ".filter(e => e.offsetParent !== null)"
        ".filter(e => e.getBoundingClientRect().height < 44).length"
    )
    assert small == 0


@pytest.mark.slow
def test_widgets_reenhance_after_live_update(open_page: Any) -> None:
    page = open_page
    doc: Path = page.doc
    doc.write_text(
        doc.read_text(encoding="utf-8") + "\nAfter the update.\n", encoding="utf-8"
    )
    page.wait_for_selector("text=After the update.")
    page.wait_for_timeout(300)
    assert page.locator(".vb-sort").count() == 2
    assert page.locator(".vb-tab").count() == 3
    assert page.locator(".flow .vd-view").count() == 1
    page.get_by_role("tab", name="error").click()
    assert "Retry" in page.locator(".vb-state:visible").inner_text()
