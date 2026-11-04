from __future__ import annotations

import test_web_browser

browser_page = test_web_browser.browser_page

ROUTES = (
    "/plans",
    "/plans/dashboard-ux2",
    "/mailbox",
    "/mailbox?thread=dashboard-ux2",
    "/",
    "/thread/manager",
    "/profile/builder",
    "/settings",
    "/settings",
)


def test_dashboard_routes_fit_390px(browser_page):
    page, _, _, origin, _ = browser_page
    page.set_viewport_size({"width": 390, "height": 844})

    for route in ROUTES:
        page.goto(f"{origin}{route}")
        if route == "/settings":
            navigation = page.get_by_role("navigation", name="Settings sections")
            navigation.locator('a[href="/settings/runner"]').wait_for()
        assert page.evaluate("document.documentElement.scrollWidth") <= 390, route
