from __future__ import annotations

from pathlib import Path

import pytest
import test_web_browser

pytestmark = pytest.mark.slow

browser_page = test_web_browser.browser_page

SHOTS = Path(
    "/Users/alec/source/agent-memory/projects/varde-py/working/plans/"
    "2026-10-21-dashboard-ux2-design/notes/shots"
)
SNAPSHOT = {
    "plans": [],
    "infrastructure": [
        {"address": "main", "paseo_id": "paseo-main-1", "status": "running"},
        {"address": "mailman", "paseo_id": "paseo-mail-2", "status": "stale"},
    ],
    "agents": [
        {"id": "a1", "title": "Explore dashboard", "status": "running"},
        {"id": "a2", "title": "Old builder", "status": "idle"},
    ],
}


def open_settings(page, origin):
    page.route("**/api/orchestrators", lambda r: r.fulfill(json=SNAPSHOT))
    test_web_browser.mock_events(page, SNAPSHOT)
    page.set_viewport_size({"width": 390, "height": 1500})
    page.goto(f"{origin}/settings/status")
    page.get_by_role("heading", name="Status", level=1).wait_for()


def test_settings_links_roles_and_shows_status(browser_page):
    page, _, _, origin, _ = browser_page
    open_settings(page, origin)
    page.goto(f"{origin}/settings")
    link = page.get_by_role("link", name="Role types")
    assert link.get_attribute("href") == "/settings/role-types"
    page.goto(f"{origin}/settings/status")
    status = page.get_by_role("region", name="Status")
    status.get_by_text("Infrastructure · 1 need attention").wait_for()
    assert status.get_by_text("mailman").is_visible()
    assert status.get_by_text("main").count() == 0
    assert status.get_by_text("Other agents · 2").is_visible()
    assert not status.get_by_text("Explore dashboard").is_visible()
    status.get_by_text("Other agents · 2").click()
    assert status.get_by_text("Explore dashboard").is_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_settings_screenshots(browser_page):
    page, _, _, origin, _ = browser_page
    open_settings(page, origin)
    SHOTS.mkdir(parents=True, exist_ok=True)
    for scheme in ("light", "dark"):
        page.emulate_media(color_scheme=scheme)
        page.goto(f"{origin}/settings/status")
        page.get_by_text("Infrastructure · 1 need attention").wait_for()
        page.screenshot(
            path=str(SHOTS / f"settings-{scheme}.jpg"),
            type="jpeg",
            quality=65,
            full_page=True,
        )
    page.emulate_media(color_scheme="light")
