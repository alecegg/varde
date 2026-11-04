"""Chromium checks of `varde learn docs serve` at phone width (slow tier)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs import cli
from varde_learn.docs.pages.comments import fold, read_rows
from varde_learn.docs.pages.serve import PageServer

pytestmark = pytest.mark.slow

WIDE = ", ".join(f'"task{i:02d}-with-a-long-name": ["root"]' for i in range(14))
DOC = (
    "# Plan\n\nAlpha paragraph.\n\nBeta paragraph.\n\nGamma paragraph.\n\n"
    f'```ui id=g\ng = deps(edges: {{"root": [], {WIDE}}})\n```\n\n'
    "```html\n<p id=w>widget</p>\n```\n"
)
VIEWPORT = {"width": 390, "height": 844}


class Page:
    def __init__(
        self, server: PageServer, thread: threading.Thread, doc: Path, page: Any
    ) -> None:
        self.server, self.thread, self.doc, self.page = server, thread, doc, page
        self.problems: list[str] = []
        self.listeners = {
            "pageerror": lambda error: self.problems.append(str(error)),
            "console": lambda msg: (
                msg.type == "error" and self.problems.append(msg.text)
            ),
        }
        for event, handler in self.listeners.items():
            page.on(event, handler)

    def detach(self) -> None:
        for event, handler in self.listeners.items():
            self.page.remove_listener(event, handler)

    def comments(self) -> list[dict[str, Any]]:
        return fold(read_rows(self.doc))


def start(doc: Path, port: int = 0) -> tuple[PageServer, threading.Thread]:
    server = PageServer(doc, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop(server: PageServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(5)


@pytest.fixture(scope="module")
def shared_page(browser_session: Any) -> Any:
    # Single-process Chromium dies when a page closes, so one page serves the module.
    page = browser_session.new_page(viewport=VIEWPORT)
    page.set_default_timeout(10_000)
    return page


@pytest.fixture
def app(tmp_path: Path, shared_page: Any) -> Iterator[Page]:
    doc = tmp_path / "plan.md"
    doc.write_text(DOC, encoding="utf-8")
    server, thread = start(doc)
    page = shared_page
    holder = Page(server, thread, doc, page)
    page.goto(f"http://127.0.0.1:{server.port}/")
    page.wait_for_selector(".menu-btn")
    yield holder
    page.goto("about:blank")
    holder.detach()
    stop(holder.server, holder.thread)


def choose(block: Any, entry: str) -> None:
    """Open the block's action menu and pick one entry."""
    block.locator(".menu-btn").click()
    block.page.locator(f'.menu-item[data-entry="{entry}"]').click()


def send_comment(page: Any, block_text: str, text: str) -> None:
    block = page.locator(".block", has_text=block_text).first
    choose(block, "comment")
    page.locator(".composer textarea").fill(text)
    page.locator(".composer .primary").click()
    page.wait_for_selector(".thread")


def test_mobile_has_no_horizontal_scroll_and_big_targets(app: Page) -> None:
    page = app.page
    metrics = page.evaluate(
        "() => ({sw: document.documentElement.scrollWidth, iw: window.innerWidth})"
    )
    assert metrics["sw"] <= metrics["iw"], metrics
    choose(page.locator(".block", has_text="Alpha").first, "comment")
    sizes = page.evaluate(
        """() => [...document.querySelectorAll('button')].map((b) => {
          const r = b.getBoundingClientRect();
          return [b.textContent, r.width, r.height];
        })"""
    )
    assert len(sizes) >= 5
    small = [s for s in sizes if s[1] < 44 or s[2] < 44]
    assert not small, small


def test_mobile_wide_graph_scrolls_inside_wrapper(app: Page) -> None:
    wrapper = app.page.locator(".scroll", has=app.page.locator("svg.dep-graph"))
    sizes = wrapper.evaluate(
        "(el) => ({scroll: el.scrollWidth, client: el.clientWidth,"
        " overflow: getComputedStyle(el).overflowX})"
    )
    assert sizes["scroll"] > sizes["client"], sizes
    assert sizes["client"] <= VIEWPORT["width"]
    assert sizes["overflow"] in ("auto", "scroll")
    page_scroll = app.page.evaluate("() => document.documentElement.scrollWidth")
    assert page_scroll <= VIEWPORT["width"]


def test_reply_via_cli_appears_without_reload(app: Page, capsys) -> None:
    page = app.page
    page.evaluate("() => { window.__same_page = true; }")
    send_comment(page, "Alpha", "please expand")
    comment_id = app.comments()[0]["id"]
    code = cli.run(["reply", str(app.doc), comment_id, "--note", "expanded it"])
    assert code == 0, capsys.readouterr().err
    page.wait_for_selector(".thread .reply >> text=expanded it", timeout=10000)
    assert page.evaluate("() => window.__same_page") is True
    assert not app.problems, app.problems


def test_highlight_marks_only_changed_blocks(app: Page) -> None:
    page = app.page
    assert page.locator(".block.changed").count() == 0
    app.doc.write_text(DOC.replace("Beta paragraph.", "Beta rewritten."), "utf-8")
    page.wait_for_selector(".block.changed", timeout=10000)
    changed = page.locator(".block.changed")
    assert changed.count() == 1
    assert "Beta rewritten" in changed.first.inner_text()
    assert not app.problems, app.problems


def test_refresh_keeps_unchanged_blocks(app: Page) -> None:
    page = app.page
    page.wait_for_selector(".block")
    page.evaluate(
        """() => {
          for (const block of document.querySelectorAll('.block')) block.__keep = true;
        }"""
    )
    app.doc.write_text(DOC.replace("Beta paragraph.", "Beta rewritten."), "utf-8")
    page.wait_for_selector(".block.changed", timeout=10000)
    kept = page.evaluate(
        """() => ({
          kept: [...document.querySelectorAll('.block')].filter((b) => b.__keep).length,
          total: document.querySelectorAll('.block').length,
        })"""
    )
    assert kept["kept"] == kept["total"] - 1
    assert not app.problems, app.problems


def test_edit_suggest_and_accept_from_the_page(app: Page) -> None:
    page = app.page
    block = page.locator(".block", has_text="Alpha").first
    choose(block, "edit")
    page.locator(".editor textarea").fill("Alpha edited.")
    page.locator(".editor .primary").click()
    page.wait_for_selector(".block:has-text('Alpha edited.')", timeout=10000)
    assert "Alpha edited." in app.doc.read_text("utf-8")
    block = page.locator(".block", has_text="Beta").first
    choose(block, "suggest")
    page.locator(".editor textarea").fill("Beta suggested.")
    page.locator(".editor .primary").click()
    page.wait_for_selector(".thread[data-kind=suggestion] ins", timeout=10000)
    assert "Beta paragraph." in app.doc.read_text("utf-8")
    page.locator(".thread[data-kind=suggestion] .accept-btn").click()
    page.wait_for_selector(".block:has-text('Beta suggested.')", timeout=10000)
    assert "Beta suggested." in app.doc.read_text("utf-8")
    assert app.comments()[0]["applied_by"] == "user"
    assert not app.problems, app.problems


def test_comment_survives_server_restart_on_same_port(app: Page) -> None:
    page = app.page
    old_token = app.server.token
    port = app.server.port
    stop(app.server, app.thread)
    app.server, app.thread = start(app.doc, port)
    assert app.server.token != old_token
    page.wait_for_function(
        "(t) => document.querySelector('meta[name=varde-token]').content === t",
        arg=app.server.token,
        timeout=15000,
    )
    send_comment(page, "Gamma", "after restart")
    assert [c["text"] for c in app.comments()] == ["after restart"]
