from __future__ import annotations

import re

import pytest
import test_web_browser
from playwright.sync_api import expect

pytestmark = pytest.mark.slow

browser_page = test_web_browser.browser_page


def test_profile_shows_read_only_role_details_on_mobile_and_desktop(browser_page):
    page, _, _, origin, _ = browser_page
    identity = {
        "id": "builder",
        "name": "Builder",
        "label": "builder",
        "description": "Implements work.",
        "role": "builder",
        "count": 1,
        "worst_state": "running",
        "instances": None,
    }
    page.route(
        "**/api/identities",
        lambda route: route.fulfill(json={"identities": [identity]}),
    )
    page.route(
        "**/api/roles",
        lambda route: route.fulfill(
            json={
                "roles": {"builder": {"type": "standard"}},
                "types": {
                    "standard": {
                        "harness": "claude-cli",
                        "model": "sonnet-5",
                        "reasoning_effort": "high",
                    }
                },
            }
        ),
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/profile/builder")

    details = page.get_by_role("region", name="Read-only configuration")
    expect(page.get_by_role("heading", name="Builder", level=2)).to_be_visible()
    expect(page.locator(".profile .avatar")).to_have_text("BU")
    expect(page.locator(".profile .avatar")).to_have_class(
        re.compile(r"avatar blue running")
    )
    expect(details.get_by_text("Claude Cli")).to_be_visible()
    expect(details.get_by_text("sonnet-5")).to_be_visible()
    expect(details.get_by_text("High")).to_be_visible()
    expect(details.get_by_text("Builder", exact=True)).to_be_visible()
    expect(
        page.locator(".chat-shell > .app-header").get_by_role(
            "link", name="Back to conversation"
        )
    ).to_have_attribute("href", "/thread/builder")
    assert page.get_by_role("textbox").count() == 0
    assert page.get_by_role("button", name="Save profile").count() == 0
    assert page.evaluate("document.documentElement.scrollWidth") <= 390

    page.set_viewport_size({"width": 1280, "height": 900})
    assert page.evaluate("document.documentElement.scrollWidth") <= 1280


def test_profile_missing_role_fields_show_not_set(browser_page):
    page, _, _, origin, _ = browser_page
    identity = {
        "id": "builder",
        "name": "Builder",
        "label": "builder",
        "description": "",
        "role": "builder",
        "count": 0,
        "worst_state": None,
        "instances": None,
    }
    page.route(
        "**/api/identities",
        lambda route: route.fulfill(json={"identities": [identity]}),
    )
    page.route(
        "**/api/roles",
        lambda route: route.fulfill(json={"roles": {}, "types": {}}),
    )
    page.goto(f"{origin}/profile/builder")
    details = page.get_by_role("region", name="Read-only configuration")
    expect(details.get_by_text("Not set")).to_have_count(3)
    expect(details.get_by_text("Builder", exact=True)).to_be_visible()
