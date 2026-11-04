from __future__ import annotations

import re

import pytest
import test_web_browser
from fakes.chat_bot import FakeChatBot, message
from playwright.sync_api import expect

pytestmark = pytest.mark.slow

browser_page = test_web_browser.browser_page


def test_manager_composer_is_enabled_when_role_is_enabled(browser_page):
    page, _, _, origin, _ = browser_page
    bot = FakeChatBot([message(1, "Welcome")])
    page.route("**/api/chat**", bot.route)
    page.route(
        "**/api/roles",
        lambda route: route.fulfill(json={"roles": {"manager-bot": {"enabled": True}}}),
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/thread/manager")

    composer = page.get_by_role("textbox", name="Message Manager…")
    expect(composer).to_be_enabled()
    assert page.evaluate("document.documentElement.scrollWidth") <= 390


def test_plan_detail_mobile_views(browser_page):
    page, _, _, origin, _ = browser_page
    page.route(
        "**/api/plans/queue-plan/task-queue",
        lambda route: route.fulfill(json={"items": [], "role_sessions": []}),
    )
    plan = {
        "id": "queue-plan",
        "title": "Queue improvements",
        "status": "backlog",
        "plan_text": "# Queue improvements\n\nA readable plan body.",
        "tasks": [
            {
                "id": "T2",
                "title": "Queue and plan UI",
                "status": "todo",
                "acceptance_criteria": ["Works on a phone"],
            }
        ],
        "notes_status": "present",
        "review_status": "none",
        "comments": [
            {
                "id": "c1",
                "ts": "2026-10-20T10:00:00Z",
                "target": "T2",
                "text": "Keep controls easy to tap.",
                "state": "open",
                "kind": "stored",
            }
        ],
    }
    page.route("**/api/plans/queue-plan", lambda route: route.fulfill(json=plan))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/plans/queue-plan")
    page.get_by_role("heading", name="Queue improvements", level=1).wait_for()
    assert (
        page.get_by_role("link", name="Back to plans").get_attribute("href") == "/plans"
    )
    expect(page.get_by_text("Keep controls easy to tap.")).to_be_visible()
    expect(page.get_by_text("Saved")).to_be_visible()
    comment = page.get_by_role("textbox", name="Comment")
    expect(comment).to_have_count(0)
    page.get_by_role("button", name="Add comment").click()
    expect(comment).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_plan_refreshes_on_mailbox_snapshot(browser_page):
    page, _, _, origin, _ = browser_page
    page.route(
        re.compile(r".*/api/plans/[^/]+/task-queue$"),
        lambda route: route.fulfill(json={"items": [], "role_sessions": []}),
    )
    count = {"plan": 0}

    def plan_route(route):
        count["plan"] += 1
        route.fulfill(
            json={
                "id": "queue-plan",
                "title": "Queue plan",
                "status": "backlog",
                "plan_text": "",
                "tasks": [],
                "notes_status": "none",
                "review_status": "none",
                "comments": [],
            }
        )

    page.route("**/api/plans/queue-plan", plan_route)
    page.goto(f"{origin}/plans/queue-plan")
    page.get_by_role("heading", name="Queue plan").wait_for()
    page.wait_for_timeout(250)
    before = count["plan"]
    page.evaluate(
        "topics => window.dispatchEvent(new CustomEvent('runner:snapshot', "
        "{detail: {topics}}))",
        ["mailbox"],
    )
    page.wait_for_timeout(250)
    assert count["plan"] > before


def test_plan_viewer_renders_markdown_and_neutralises_hostile_input(browser_page):
    page, _, _, origin, _ = browser_page
    page.route(
        "**/api/plans/*/task-queue",
        lambda route: route.fulfill(json={"items": [], "role_sessions": []}),
    )
    plan_text = (
        "# Title\n\n## Steps\n\n- first item\n- second item\n\n```\nprint('x')\n```\n\n"
        '<img src=x onerror="window.__pwned=1"> [bad](javascript:window.__pwned=1) '
        "[proto](//evil.example/a) [ok](https://example.com/a) "
        "[e](https://a.example/**b**)\n"
    )
    plan = {
        "id": "md-plan",
        "title": "Markdown plan",
        "status": "backlog",
        "plan_text": plan_text,
        "tasks": [],
        "notes_status": "present",
        "review_status": "none",
        "comments": [],
    }
    page.route("**/api/plans/md-plan", lambda route: route.fulfill(json=plan))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/plans/md-plan")
    markdown = page.locator(".markdown")
    markdown.wait_for()
    assert markdown.get_by_role("heading", name="Steps").is_visible()
    assert markdown.locator("li").count() == 2
    assert markdown.locator("pre code").inner_text() == "print('x')"
    assert markdown.locator("img").count() == 0
    assert page.evaluate("window.__pwned") is None
    hrefs = markdown.locator("a").evaluate_all(
        "els => els.map(e => e.getAttribute('href'))"
    )
    assert hrefs == ["https://example.com/a"]
    assert markdown.locator("a").get_attribute("rel") == "noopener noreferrer"
    assert "[bad](javascript:" in markdown.inner_text()
