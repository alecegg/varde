from __future__ import annotations

import os

import pytest
import test_web_browser

pytestmark = pytest.mark.slow

browser_page = test_web_browser.browser_page


def test_non_plan_permission_escalation_is_actionable_and_answerable(browser_page):
    page, _, _, origin, _ = browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    state = {"open": True, "answers": []}
    thread = {
        "thread_id": "guard:session:1",
        "plan_id": None,
        "sender": "Guard",
        "title": "Permission request",
        "open_count": int(state["open"]),
        "last_ts": "2026-10-23T10:00:00Z",
        "last_preview": "Allow git status?",
        "decision_ids": ["perm:1"],
    }
    permission = {
        "msg_id": "perm:1",
        "thread_id": thread["thread_id"],
        "sender": "Guard",
        "title": "Permission request",
        "asked": "Allow git status?",
        "kind": "permission",
        "state": "pending",
        "ts": "2026-10-23T10:00:00Z",
    }

    page.route(
        "**/events",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )

    def threads(route):
        route.fulfill(json=[{**thread, "open_count": int(state["open"])}])

    page.route("**/api/threads", threads)
    page.route(
        "**/api/mailbox?**",
        lambda route: route.fulfill(
            json={"items": [{**permission, "mailbox_open": state["open"]}]}
        ),
    )
    page.route(
        "**/api/mailbox/perm%3A1",
        lambda route: route.fulfill(json={**permission, "mailbox_open": state["open"]}),
    )

    def answer(route):
        state["answers"].append(route.request.post_data_json)
        state["open"] = False
        route.fulfill(
            json={
                "status": "delivered",
                "reply": "ALLOW",
                "sent_at": "2026-10-23T10:01:00Z",
            }
        )

    page.route("**/api/mailbox/*/answer", answer)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/threads/guard%3Asession%3A1")
    page.locator(".thread-head").get_by_role(
        "heading", name="Guard", exact=True
    ).wait_for()
    page.reload()
    page.locator(".thread-head").get_by_role(
        "heading", name="Guard", exact=True
    ).wait_for()
    page.locator(".thread-head").get_by_role(
        "heading", name="Guard", exact=True
    ).wait_for()
    shots = os.environ.get("VARDE_SHOTS_DIR")
    if shots:
        page.screenshot(path=f"{shots}/needs-you-thread-390.png")
    with page.expect_response("**/api/mailbox/**/answer"):
        page.get_by_role("button", name="Allow").click()
    assert len(state["answers"]) == 1
    assert state["answers"][0]["option"] == "allow"
    assert state["answers"][0]["text"] == ""
    assert page.locator(".thread").evaluate("node => node.scrollWidth <= innerWidth")


def test_open_sender_request_is_visible_in_needs_action_and_old_lists_redirect(
    browser_page,
):
    page, _, _, origin, _ = browser_page
    shots_dir = os.environ.get("VARDE_SHOTS_DIR")
    threads = [
        {
            "thread_id": "sender:varde-builder",
            "plan_id": None,
            "sender": "varde-builder",
            "title": "Open question",
            "open_count": 1,
            "last_ts": "2099-10-23T10:00:00Z",
            "last_preview": "Which option should we use?",
            "decision_ids": ["open-question"],
            "user_message": True,
        },
        {
            "thread_id": "sender:agent-update",
            "plan_id": None,
            "sender": "builder",
            "title": "Internal agent update",
            "open_count": 1,
            "last_ts": "2099-10-24T10:00:00Z",
            "last_preview": "Agent-only content",
            "decision_ids": ["agent-update"],
            "user_message": False,
        },
    ]
    decisions = [
        {
            "msg_id": "open-question",
            "thread_id": "sender:varde-builder",
            "kind": "needs-user",
            "type": "question",
            "mailbox_open": True,
            "sender": "varde-builder",
            "agent_title": "Builder",
            "title": "Open question",
            "asked": "Which option should we use?",
            "state": "pending",
        },
        {
            "msg_id": "agent-update",
            "thread_id": "sender:agent-update",
            "kind": "agent-message",
            "mailbox_open": True,
            "sender": "builder",
            "title": "Internal agent update",
            "asked": "Agent-only content",
            "state": "pending",
        },
    ]
    page.route(
        "**/events",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.route(
        "**/api/threads",
        lambda route: route.fulfill(json=threads),
    )
    page.route(
        "**/api/mailbox?**",
        lambda route: route.fulfill(json={"items": decisions}),
    )
    page.route(
        "**/api/mailbox/open-question",
        lambda route: route.fulfill(json=decisions[0]),
    )
    page.route("**/api/agents", lambda route: route.fulfill(json=[]))
    page.route("**/api/degraded", lambda route: route.fulfill(json={"sources": []}))
    page.set_viewport_size({"width": 390, "height": 844})
    for path in ("/mailbox", "/threads"):
        page.goto(f"{origin}{path}")
        assert page.url == f"{origin}/"

    page.goto(f"{origin}/chat/needs")
    page.get_by_role("heading", name="Needs action").wait_for()
    card = page.locator(".work-item").filter(has_text="Which option should we use?")
    card.wait_for()
    assert card.get_by_role("heading", name="Builder · Open question").is_visible()
    assert page.get_by_text("Agent-only content").count() == 0
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if shots_dir:
        page.screenshot(path=f"{shots_dir}/needs-390.png", full_page=True)


def test_needs_list_renders_each_open_decision_from_same_thread(browser_page):
    page, _, _, origin, _ = browser_page
    decisions = [
        {
            "msg_id": "m-open",
            "thread_id": "plan:plan-1",
            "kind": "needs-user",
            "type": "question",
            "mailbox_open": True,
            "sender": "builder",
            "title": "Approve the plan?",
            "asked": "Should we proceed with the plan?",
            "state": "pending",
        },
        {
            "msg_id": "m-merge2",
            "thread_id": "plan:plan-1",
            "kind": "merge-ready",
            "type": "approval",
            "mailbox_open": True,
            "sender": "builder",
            "title": "Plan is ready to merge",
            "asked": "May I merge the completed work?",
            "state": "pending",
        },
    ]
    page.route(
        "**/api/threads",
        lambda route: route.fulfill(
            json=[
                {
                    "thread_id": "plan:plan-1",
                    "plan_id": "plan-1",
                    "sender": "builder",
                    "title": "Plan 1",
                    "open_count": 2,
                    "last_ts": "2099-10-28T10:00:00Z",
                    "last_preview": "Plan 1 update",
                    "decision_ids": [item["msg_id"] for item in decisions],
                }
            ]
        ),
    )
    page.route(
        "**/api/mailbox?**",
        lambda route: route.fulfill(json={"items": decisions}),
    )
    page.route(
        "**/api/mailbox/*",
        lambda route: route.fulfill(
            json=next(
                item for item in decisions if route.request.url.endswith(item["msg_id"])
            )
        ),
    )
    page.route("**/api/agents", lambda route: route.fulfill(json=[]))
    page.route("**/api/degraded", lambda route: route.fulfill(json={"sources": []}))
    answers = []

    def answer(route):
        answers.append((route.request.url, route.request.post_data_json))
        route.fulfill(json={"status": "delivered"})

    page.route("**/api/mailbox/*/answer", answer)
    page.goto(f"{origin}/chat/needs")
    cards = page.locator(".chat-needs .work-item")
    page.get_by_text("Should we proceed with the plan?", exact=True).wait_for()
    page.get_by_text("May I merge the completed work?", exact=True).wait_for()
    assert cards.count() == 2
    merge_card = cards.filter(has_text="May I merge the completed work?")
    with page.expect_response("**/api/mailbox/m-merge2/answer"):
        merge_card.get_by_role("button", name="Allow").click()
