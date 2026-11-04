from __future__ import annotations

import pytest
import test_web_browser

pytestmark = pytest.mark.slow

browser_page = test_web_browser.browser_page


def test_menu_sheet_navigation_and_touch_target(browser_page):
    page, _, _, origin, _ = browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/")
    trigger = page.get_by_role("button", name="Open menu")
    assert trigger.bounding_box()["width"] >= 44
    assert trigger.bounding_box()["height"] >= 44
    trigger.click()
    menu = page.get_by_role("dialog")
    menu.wait_for()
    links = menu.get_by_role("navigation", name="Main menu").get_by_role("link")
    assert [links.nth(i).get_attribute("href") for i in range(links.count())] == [
        "/",
        "/plans",
        "/settings",
    ]
    for link in links.all():
        box = link.bounding_box()
        assert box["height"] >= 44
    links.get_by_text("Conversations").click()
    page.wait_for_url(f"{origin}/")
    assert page.url == f"{origin}/"


def test_retired_routes_redirect_to_current_screens(browser_page):
    page, _, _, origin, _ = browser_page
    redirects = {
        "/home": "/",
        "/chats": "/",
        "/queue": "/thread/manager",
        "/new-item": "/thread/manager",
        "/agents": "/settings",
        "/roles": "/settings/role-types",
        "/queue/builder": "/thread/builder",
        "/agents/profile/builder": "/profile/builder",
    }
    for old_path, new_path in redirects.items():
        page.goto(f"{origin}{old_path}")
        page.wait_for_url(f"**{new_path}")
        assert page.url.endswith(new_path), old_path

    page.goto(f"{origin}/chat")
    page.get_by_role("heading", name="Chats", level=1).wait_for()
