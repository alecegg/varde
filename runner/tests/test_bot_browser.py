"""Browser checks of the manager-bot controls and the pairing screen (fake API).

Skipped with a stated reason when the runner UI is not built (`just build-ui`).
Every check runs at 390px and 1280px: no horizontal scroll and no left-border stripe.
"""

from __future__ import annotations

import re

import pytest
from fakes.chat_bot import FakeChatBot, message

pytestmark = pytest.mark.slow

pytest_plugins = ("test_web_browser",)

VIEWPORTS = [(390, 844), (1280, 900)]
CODE = "ABCD2345"


class FakeBotApi:
    """Scripted `/api/bot/*` and `/api/pairing` responses."""

    def __init__(self, *, paired: bool = True, enforced: bool = True) -> None:
        self.state = "running"
        self.paired = paired
        self.enforced = enforced
        self.controls: list[str] = []
        self.pairing_attempts: list[str] = []
        self.audit = [
            {
                "id": 2,
                "phase": "call",
                "action": "POST /api/mailbox/{decision_id:str}/dismiss",
                "actor": "bot:manager",
                "status": "denied",
                "reason": "this route is for the user only",
                "agent_id": None,
                "plan_id": None,
                "ts": "2026-10-26T10:00:00Z",
            },
            {
                "id": 1,
                "phase": "call",
                "action": "launch",
                "actor": "bot:manager",
                "status": "allowed",
                "reason": None,
                "agent_id": "agent-1",
                "plan_id": None,
                "ts": "2026-10-26T09:59:00Z",
            },
        ]

    def snapshot(self) -> dict:
        return {
            "state": self.state,
            "reason": "paused by user" if self.state == "paused" else None,
            "changed_at": None,
            "changed_by": None,
            "agents": 1,
            "max_concurrent_agents": 4,
            "launches_last_hour": 1,
            "max_launches_per_hour": 6,
            "actions_last_minute": 2,
            "max_actions_per_minute": 30,
            "tokens_today": 1000,
            "daily_token_budget": 5_000_000,
        }

    def route(self, route) -> None:
        request = route.request
        path = request.url.split("?")[0].removeprefix(request.url.split("/api/")[0])
        if path == "/api/bot/state":
            route.fulfill(json=self.snapshot())
        elif path == "/api/bot/control" and request.method == "POST":
            action = request.post_data_json["action"]
            self.controls.append(action)
            self.state = {"pause": "paused", "resume": "running", "kill": "killed"}[
                action
            ]
            route.fulfill(json=self.snapshot())
        elif path == "/api/bot/audit":
            route.fulfill(json=self.audit)
        elif path == "/api/pairing" and request.method == "POST":
            code = request.post_data_json["code"]
            self.pairing_attempts.append(code)
            if code != CODE:
                route.fulfill(status=403, json={"error": "pairing code refused"})
                return
            self.paired = True
            route.fulfill(json={"paired": True, "csrf": "csrf-token"})
        elif path == "/api/pairing":
            route.fulfill(
                json={
                    "enforced": self.enforced,
                    "paired": self.paired,
                    "csrf": "csrf-token" if self.paired else None,
                }
            )
        else:
            route.continue_()


def open_chat(page, origin, bot_api: FakeBotApi, width: int, height: int) -> None:
    chat = FakeChatBot([message(1, "Welcome")])
    page.route("**/api/chat**", chat.route)
    page.route("**/api/bot/**", bot_api.route)
    page.route("**/api/pairing", bot_api.route)
    page.route(
        "**/api/roles",
        lambda route: route.fulfill(json={"roles": {"manager-bot": {"enabled": True}}}),
    )
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{origin}/thread/manager")
    page.get_by_role("region", name="Manager bot controls").wait_for()


def open_menu(controls) -> None:
    controls.get_by_role(
        "button", name=re.compile("more|menu|actions", re.IGNORECASE)
    ).click()


def assert_no_overflow_or_stripe(page, width: int) -> None:
    assert page.locator("body").evaluate("el => el.scrollWidth") <= width
    assert page.locator(
        "section, article, dialog, [role=dialog], [role=status]"
    ).evaluate_all(
        "els => els.every(el => { const s = getComputedStyle(el);"
        " return s.borderLeftWidth === s.borderTopWidth"
        " && s.borderLeftColor === s.borderTopColor; })"
    )


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_pause_banner_resume_and_chip(browser_page, width, height) -> None:
    page, _, _, origin, _ = browser_page
    bot = FakeBotApi()
    open_chat(page, origin, bot, width, height)
    controls = page.get_by_role("region", name="Manager bot controls")
    controls.get_by_role("button", name="Pause").wait_for()
    controls.get_by_role("button", name="Pause").click()
    controls.get_by_role("button", name="Resume").wait_for()
    banner = page.get_by_role("status").filter(has_text="Chat is paused")
    banner.wait_for()
    assert_no_overflow_or_stripe(page, width)
    controls.get_by_role("button", name="Resume").click()
    controls.get_by_role("button", name="Pause").wait_for()
    banner.wait_for(state="detached")
    assert bot.controls == ["pause", "resume"]


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_kill_needs_the_confirm_dialog(browser_page, width, height) -> None:
    page, _, _, origin, _ = browser_page
    bot = FakeBotApi()
    open_chat(page, origin, bot, width, height)
    controls = page.get_by_role("region", name="Manager bot controls")
    controls.get_by_role("button", name="Pause").wait_for()
    assert page.get_by_role("button", name="Kill bot").count() == 0
    open_menu(controls)
    page.get_by_role("menuitem", name=re.compile("Kill bot")).click()
    dialog = page.get_by_role("dialog", name="Kill the manager bot?")
    dialog.wait_for()
    assert bot.controls == []
    assert_no_overflow_or_stripe(page, width)
    dialog.get_by_role("button", name="Cancel").click()
    dialog.wait_for(state="detached")
    assert bot.controls == []
    open_menu(controls)
    page.get_by_role("menuitem", name=re.compile("Kill bot")).click()
    page.get_by_role("dialog").get_by_role("button", name="Kill bot").click()
    page.get_by_role("status").filter(has_text="The manager bot was killed").wait_for()
    assert page.get_by_role("textbox", name="Message").is_disabled()
    assert bot.controls == ["kill"]


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_audit_sheet_lists_rows_newest_first_with_the_bot_badge(
    browser_page, width, height
) -> None:
    page, _, _, origin, _ = browser_page
    bot = FakeBotApi()
    open_chat(page, origin, bot, width, height)
    controls = page.get_by_role("region", name="Manager bot controls")
    open_menu(controls)
    page.get_by_role("menuitem", name="View audit").click()
    sheet = page.get_by_role("dialog", name="Bot audit")
    sheet.wait_for()
    items = sheet.get_by_role("listitem")
    items.nth(1).wait_for()
    assert "dismiss" in items.nth(0).inner_text()
    assert "launch" in items.nth(1).inner_text()
    assert sheet.get_by_label("Actor: Manager bot").count() == 2
    assert items.nth(1).get_by_role("link", name="agent-1").is_visible()
    assert_no_overflow_or_stripe(page, width)


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_pairing_wrong_code_is_refused_then_the_right_code_pairs_once(
    browser_page, width, height
) -> None:
    page, _, _, origin, _ = browser_page
    bot = FakeBotApi(paired=False)
    page.route("**/api/bot/**", bot.route)
    page.route("**/api/pairing", bot.route)
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{origin}/")
    page.get_by_role("heading", name="Pair this browser").wait_for()
    field = page.get_by_label("Pairing code")
    field.fill("WRONG-CODE")
    page.get_by_role("button", name="Pair", exact=True).click()
    page.get_by_text("pairing code refused").wait_for()
    assert bot.paired is False
    assert_no_overflow_or_stripe(page, width)
    field.fill(CODE)
    page.get_by_role("button", name="Pair", exact=True).click()
    page.get_by_role("heading", name="Pair this browser").wait_for(state="detached")
    assert bot.paired is True
    assert bot.pairing_attempts == ["WRONG-CODE", CODE]


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_disabled_pairing_gate_does_not_show_a_pairing_prompt(
    browser_page, width, height
) -> None:
    page, _, _, origin, _ = browser_page
    bot = FakeBotApi(paired=False, enforced=False)
    page.route("**/api/pairing", bot.route)
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{origin}/")
    page.locator(".chat-list" if width < 900 else ".desktop-chat-sidebar").wait_for()
    assert page.get_by_role("heading", name="Pair this browser").count() == 0
