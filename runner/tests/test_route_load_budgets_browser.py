from __future__ import annotations

import os
import time

import pytest
import test_web_browser

pytestmark = pytest.mark.slow
browser_page = test_web_browser.browser_page


@pytest.mark.parametrize(
    ("route", "path", "role", "name", "budget_ms"),
    [
        ("shell ready", "/", "button", "Open menu", 2_300),
        ("chat list", "/", "heading", "Chats", 1_200),
        ("plans", "/plans", "heading", "Plans", 1_700),
    ],
)
def test_key_route_load_budget(browser_page, route, path, role, name, budget_ms):
    page, _, _, origin, _ = browser_page
    timings = []
    multiplier = float(os.environ.get("VARDE_BROWSER_LOAD_BUDGET_MULTIPLIER", "1"))
    effective_budget_ms = budget_ms * multiplier
    level = 1 if role == "heading" else None
    page.goto(f"{origin}{path}")
    page.get_by_role(role, name=name, exact=True, level=level).wait_for(state="visible")
    for _ in range(7):
        started = time.perf_counter()
        page.goto(f"{origin}{path}")
        page.get_by_role(role, name=name, exact=True, level=level).wait_for(
            state="visible"
        )
        timings.append((time.perf_counter() - started) * 1000)

    median_ms = sorted(timings)[len(timings) // 2]
    runs = [round(value) for value in timings]
    assert median_ms <= effective_budget_ms, (
        f"{route} median of {len(timings)} warm loads was {median_ms:.0f} ms; "
        f"budget is {effective_budget_ms:.0f} ms "
        f"(base {budget_ms} ms × {multiplier:g}; runs: {runs})"
    )
