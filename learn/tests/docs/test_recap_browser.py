"""Chromium proof of the recap page at phone width (slow tier)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.comments import fold, read_rows
from varde_learn.docs.pages.serve import PageServer

from .test_recap_page import recap_data, recap_fence

pytestmark = pytest.mark.slow

PHONE = {"width": 390, "height": 844}


@pytest.fixture
def site(tmp_path: Path) -> Iterator[tuple[PageServer, Path]]:
    doc = tmp_path / "plan.md"
    long_name = "src/" + "very_long_directory_name/" * 6 + "module_with_long_name.py"
    data = recap_data()
    data["rows"][0]["file"] = long_name
    data["rows"][0]["hunk"] = "@@ -1 +1 @@\n+" + "x" * 400
    data["untouched"][0]["owns"] = "a/" * 60 + "file.py"
    doc.write_text("# Plan\n\nNarrative.\n\n" + recap_fence(data))
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, doc
    server.shutdown()
    server.server_close()
    thread.join(5)


@pytest.fixture(scope="module")
def shared_page(browser_session: Any) -> Any:
    page = browser_session.new_page(viewport=PHONE)
    page.set_default_timeout(10_000)
    return page


def test_buttons_write_drift_rows_without_horizontal_scroll(
    shared_page: Any, site: tuple[PageServer, Path]
) -> None:
    server, doc = site
    page = shared_page
    page.goto(f"http://127.0.0.1:{server.port}/")
    page.wait_for_selector(".recap-verdict")
    page.wait_for_timeout(500)
    widths = page.evaluate(
        "() => [document.documentElement.scrollWidth,"
        " document.documentElement.clientWidth]"
    )
    assert widths[0] <= widths[1], widths
    items = page.locator(".recap-item")
    assert items.count() == 3
    items.nth(0).locator('[data-verdict="accepted"]').click()
    items.nth(1).locator('[data-verdict="rejected"]').click()
    items.nth(2).locator('[data-verdict="open"]').click()
    page.wait_for_function(
        "() => document.querySelectorAll('.recap-item[data-verdict]').length === 3"
    )
    rows = [c for c in fold(read_rows(doc)) if c.get("kind") == "drift"]
    got = {(r["item"], r["verdict"]) for r in rows}
    assert got == {
        ("unplanned:stray.txt", "accepted"),
        ("untouched:t2-model:" + "a/" * 60 + "file.py", "rejected"),
        ("unverified:model", "open"),
    }
    assert {r["anchor"] for r in rows} == {"rc"}
    page.wait_for_timeout(500)
    after = page.evaluate(
        "() => [document.documentElement.scrollWidth,"
        " document.documentElement.clientWidth]"
    )
    assert after[0] <= after[1], after
    page.goto("about:blank")
