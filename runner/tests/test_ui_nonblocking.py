from __future__ import annotations

import json

import test_web_browser

browser_page = test_web_browser.browser_page


def plan_snapshot(title):
    return [
        {
            "id": "cached-plan",
            "title": title,
            "label": title,
            "status": "in_progress",
            "queue_position": None,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        }
    ]


def seed_plan_cache(page, origin, data, *, age_ms=0):
    value = json.dumps(data)
    page.add_init_script(
        "if (location.pathname === '/plans') localStorage.setItem("
        "'varde:cache:plans:v1', JSON.stringify({version: 1, "
        f"savedAt: Date.now() - {age_ms}, value: {value}}}));"
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/plans", wait_until="domcontentloaded")


def test_plans_show_cached_data_while_refresh_is_pending(browser_page):
    page, _, _, origin, _ = browser_page
    pending = []

    def hold_request(route):
        pending.append(route)

    page.route("**/api/plans", hold_request)
    seed_plan_cache(page, origin, plan_snapshot("Cached plan"))
    page.get_by_text("Cached plan").wait_for(state="visible", timeout=3000)
    assert pending, "refresh should still be pending when cached data is shown"
    pending[0].fulfill(json=plan_snapshot("Fresh plan"))
    page.get_by_text("Fresh plan").wait_for(state="visible")


def test_stale_plans_cache_is_ignored(browser_page):
    page, _, _, origin, _ = browser_page
    page.route("**/api/plans", lambda route: None)
    seed_plan_cache(page, origin, plan_snapshot("Expired plan"), age_ms=4 * 3600 * 1000)
    page.get_by_role("status").get_by_text("Loading", exact=True).wait_for(timeout=3000)
    assert page.get_by_text("Expired plan").count() == 0
