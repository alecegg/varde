from __future__ import annotations

import os

import pytest
import test_web_browser

pytestmark = pytest.mark.slow

browser_page = test_web_browser.browser_page

PLAN = "mail-plan"
THREADS = [
    {
        "thread_id": "older",
        "plan_id": PLAN,
        "sender": "builder-old",
        "title": "Old thread",
        "open_count": 0,
        "last_ts": "2026-10-20T10:00:00Z",
        "decision_ids": ["old-answer"],
    },
    {
        "thread_id": "newer",
        "plan_id": PLAN,
        "sender": "builder-new",
        "title": "New thread",
        "open_count": 2,
        "last_ts": "2026-10-22T10:00:00Z",
        "decision_ids": ["newer-question", "newest-question"],
    },
    {
        "thread_id": "middle",
        "plan_id": PLAN,
        "sender": "builder-middle",
        "title": "Middle thread",
        "open_count": 1,
        "last_ts": "2026-10-21T10:00:00Z",
        "decision_ids": ["middle-question"],
    },
]
DECISIONS = {
    "newer-question": {
        "msg_id": "newer-question",
        "sender": "builder-new",
        "plan_id": PLAN,
        "title": "Earlier question",
        "asked": "Earlier context.",
        "kind": "needs-user",
        "ts": "2026-10-22T09:00:00Z",
        "state": "pending",
        "options": [{"label": "Today"}, {"label": "Tomorrow"}],
    },
    "newest-question": {
        "msg_id": "newest-question",
        "sender": "builder-new",
        "plan_id": PLAN,
        "title": "Newest question",
        "asked": "Newest context.",
        "kind": "needs-user",
        "ts": "2026-10-22T10:00:00Z",
        "state": "pending",
        "options": [{"label": "Accept"}, {"label": "Wait"}],
    },
    "middle-question": {
        "msg_id": "middle-question",
        "sender": "builder-middle",
        "plan_id": PLAN,
        "title": "Middle question",
        "asked": "Middle context.",
        "kind": "needs-user",
        "ts": "2026-10-21T10:00:00Z",
        "state": "pending",
        "options": [{"label": "Yes"}, {"label": "No"}],
    },
    "old-answer": {
        "msg_id": "old-answer",
        "sender": "builder-old",
        "plan_id": PLAN,
        "title": "Old decision",
        "asked": "Already settled.",
        "kind": "needs-user",
        "ts": "2026-10-20T10:00:00Z",
        "state": "delivered",
    },
}


def plan():
    return {
        "id": PLAN,
        "title": "Mail plan",
        "status": "active",
        "plan_text": "Plan details",
        "tasks": [],
        "notes_status": "none",
        "review_status": "none",
        "comments": [],
    }


def test_plan_mail_is_newest_first_actionable_and_mobile(browser_page):  # noqa: PLR0915
    from urllib.parse import parse_qs, urlparse

    page, _, _, origin, _ = browser_page
    state = {
        "open": {"newer-question", "newest-question", "middle-question"},
        "answers": [],
        "replies": {},
        "dismissed": set(),
    }
    page.route(
        "**/events",
        lambda route: route.fulfill(
            content_type="text/event-stream", body="event: update\ndata: {}\n\n"
        ),
    )
    page.route(f"**/api/plans/{PLAN}", lambda route: route.fulfill(json=plan()))
    page.route(
        f"**/api/plans/{PLAN}/task-queue",
        lambda route: route.fulfill(json={"items": [], "role_sessions": []}),
    )

    def threads(route):
        rows = [dict(item) for item in THREADS]
        for row in rows:
            row["open_count"] = sum(
                item in state["open"] for item in row["decision_ids"]
            )
        route.fulfill(json=rows)

    page.route("**/api/threads", threads)

    def mailbox(route):
        url = urlparse(route.request.url)
        if "ids" in parse_qs(url.query):
            ids = parse_qs(url.query)["ids"]
            route.fulfill(
                json={
                    "items": [
                        {
                            **DECISIONS[item_id],
                            **state["replies"].get(item_id, {}),
                            **(
                                {"state": "dismissed"}
                                if item_id in state["dismissed"]
                                else {}
                            ),
                            "mailbox_open": item_id in state["open"],
                            "summary_only": True,
                        }
                        for item_id in ids
                        if item_id in DECISIONS
                    ]
                }
            )
            return
        item_id = url.path.rsplit("/", 1)[-1]
        route.fulfill(
            json={
                **DECISIONS[item_id],
                **state["replies"].get(item_id, {}),
                **({"state": "dismissed"} if item_id in state["dismissed"] else {}),
                "mailbox_open": item_id in state["open"],
            }
        )

    page.route("**/api/mailbox**", mailbox)

    def answer(route):
        body = route.request.post_data_json
        item_id = urlparse(route.request.url).path.rsplit("/", 2)[-2]
        state["answers"].append(body)
        state["open"].discard(item_id)
        state["replies"][item_id] = {
            "state": "delivered",
            "reply": body.get("option") or body["text"],
            "sent_at": "2026-10-23T10:00:00Z",
        }
        route.fulfill(
            json={
                "status": "delivered",
                "reply": body.get("option", "Today"),
                "sent_at": "2026-10-23T10:00:00Z",
            }
        )

    page.route("**/api/mailbox/*/answer", answer)
    dismissed = []

    def dismiss(route):
        dismissed.append(route.request.url)
        item_id = urlparse(route.request.url).path.rsplit("/", 2)[-2]
        state["open"].discard(item_id)
        state["dismissed"].add(item_id)
        route.fulfill(json={"dismissed": True, "msg_id": item_id})

    page.route("**/api/mailbox/*/dismiss", dismiss)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/plans/{PLAN}")
    page.get_by_role("heading", name="Mail plan").first.wait_for()
    mail = page.locator("#mail")
    mail.get_by_role("heading", name="Newest question").wait_for()
    headings = mail.locator(".thread .card h3").all_inner_texts()
    assert headings[:3] == ["Newest question", "Earlier question", "Middle question"]
    assert mail.locator(".thread-label").all_inner_texts() == [
        "builder-new",
        "builder-middle",
        "builder-old",
    ]
    assert page.get_by_text("Needs input", exact=True).is_visible()
    bars = mail.locator(".pinned-bar")
    assert bars.count() == 2
    assert bars.evaluate_all(
        "bars => bars.every(bar => getComputedStyle(bar).position === 'static')"
    )
    reply_ids = mail.locator("textarea").evaluate_all(
        "nodes => nodes.map(node => node.id)"
    )
    assert len(reply_ids) == len(set(reply_ids))
    assert mail.evaluate("node => node.scrollWidth <= innerWidth")

    composer = mail.get_by_role("textbox", name="Reply").first
    composer.scroll_into_view_if_needed()
    assert composer.is_visible()
    box = composer.bounding_box()
    reply_bar = composer.locator("xpath=ancestor::div[contains(@class, 'pinned-bar')]")
    reply_bar_box = reply_bar.bounding_box()
    assert (
        box
        and reply_bar_box
        and box["y"] >= 0
        and box["y"] + box["height"] <= page.viewport_size["height"]
        and box["y"] >= reply_bar_box["y"]
        and box["y"] + box["height"] <= reply_bar_box["y"] + reply_bar_box["height"]
    )
    assert page.evaluate(
        """([x,y]) => document.elementFromPoint(x,y)?.tagName === 'TEXTAREA'""",
        [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2],
    )

    comment = page.get_by_role("textbox", name="Comment")
    assert comment.count() == 0
    page.get_by_role("button", name="Add comment").click()
    comment.wait_for(state="visible")
    comment.scroll_into_view_if_needed()
    assert comment.is_visible()
    comment_box = comment.bounding_box()
    assert (
        comment_box
        and comment_box["y"] >= 0
        and comment_box["y"] + comment_box["height"] <= page.viewport_size["height"]
    )
    assert page.evaluate(
        """([x,y]) => document.elementFromPoint(x,y)?.tagName === 'TEXTAREA'""",
        [
            comment_box["x"] + comment_box["width"] / 2,
            comment_box["y"] + comment_box["height"] / 2,
        ],
    )

    shots = os.environ.get("VARDE_SHOTS_DIR")
    if shots:
        page.screenshot(path=f"{shots}/plan-mail-thread.png")

    newest = mail.get_by_role("heading", name="Newest question").locator("xpath=../..")
    dismiss_open = newest.get_by_role("button", name="Dismiss")
    dismiss_open.wait_for()
    dismiss_open.click()
    dismiss_open.wait_for(state="detached")
    assert len(dismissed) == 1

    mail.get_by_text("Today", exact=True).click()
    mail.get_by_label("Reply").first.fill("Ship with the existing safe default")
    page.get_by_role("button", name="Send answer").first.click()
    assert state["answers"]
    assert state["answers"][0]["option"] == "Today"
    assert state["answers"][0]["text"] == "Ship with the existing safe default"
    assert state["answers"][0]["idempotency_key"]
    mail.locator(".sent-reply .bubble").first.wait_for()
    assert "to Builder New" in mail.locator(".sent-reply .tag").first.inner_text()
    assert page.get_by_text("Needs input", exact=True).is_visible()

    state["open"].clear()
    page.evaluate(
        "window.dispatchEvent(new CustomEvent('runner:snapshot', "
        "{detail: {topics: ['mailbox']}}))"
    )
    page.get_by_text("Needs input", exact=True).wait_for(state="hidden")
    state["open"].add("newer-question")
    page.evaluate(
        "window.dispatchEvent(new CustomEvent('runner:snapshot', "
        "{detail: {topics: ['mailbox']}}))"
    )
    page.get_by_text("Needs input", exact=True).wait_for()
    assert page.locator(".opt").count() >= 2
