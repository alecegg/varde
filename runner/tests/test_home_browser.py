from __future__ import annotations

import os

import pytest
import test_web_browser

pytestmark = pytest.mark.slow

browser_page = test_web_browser.browser_page


def test_chat_list_shows_needs_bubble_and_empty_state(browser_page):
    page, _, _, origin, _ = browser_page
    page.route(
        "**/api/threads",
        lambda route: route.fulfill(
            json=[
                {
                    "thread_id": "sender:empty",
                    "sender": "varde-builder",
                    "title": "Builder",
                    "open_count": 0,
                    "stale_count": 0,
                    "last_ts": "2026-10-27T10:00:00Z",
                    "last_preview": "",
                    "decision_ids": [],
                }
            ]
        ),
    )
    page.route("**/api/mailbox?**", lambda route: route.fulfill(json={"items": []}))
    page.route("**/api/agents", lambda route: route.fulfill(json=[]))
    page.route(
        "**/api/instance-threads**", lambda route: route.fulfill(json={"threads": []})
    )
    page.route(
        "**/api/chat?thread=main**",
        lambda route: route.fulfill(json={"messages": [], "latest_seq": 0}),
    )
    page.route(
        "**/api/needs-you-count",
        lambda route: route.fulfill(json={"needs_you_count": 0}),
    )
    page.route("**/api/degraded", lambda route: route.fulfill(json={"sources": []}))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/")
    page.locator(".chat-list .empty").get_by_text(
        "No conversations yet", exact=True
    ).wait_for()
    page.get_by_role("link", name="Needs action, 0 pending").wait_for(state="detached")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_chat_list_shows_open_sender_request_with_readable_title(browser_page):
    page, _, _, origin, _ = browser_page
    page.route(
        "**/api/threads",
        lambda route: route.fulfill(
            json=[
                {
                    "thread_id": "sender:varde-builder",
                    "plan_id": None,
                    "sender": "varde-builder",
                    "title": "Run command: /bin/zsh -lc 'git status'",
                    "open_count": 1,
                    "stale_count": 0,
                    "last_ts": "2099-10-23T10:00:00Z",
                    "last_preview": "Run command: /bin/zsh -lc 'git status'",
                    "decision_ids": ["request-1"],
                    "user_message": True,
                }
            ]
        ),
    )
    page.route(
        "**/api/mailbox?**",
        lambda route: route.fulfill(
            json={
                "items": [
                    {
                        "msg_id": "request-1",
                        "kind": "permission",
                        "type": "approval",
                        "mailbox_open": True,
                        "sender": "varde-builder",
                        "title": "Needs approval",
                        "state": "pending",
                        "asked": "Run command: /bin/zsh -lc 'git status'",
                        "body": "Builder requests permission to run git status.",
                        "options": [
                            {"id": "allow", "label": "Allow"},
                            {"id": "deny", "label": "Deny"},
                        ],
                    }
                ]
            }
        ),
    )
    page.route("**/api/agents", lambda route: route.fulfill(json=[]))
    page.route(
        "**/api/instance-threads**", lambda route: route.fulfill(json={"threads": []})
    )
    page.route(
        "**/api/chat?thread=main**",
        lambda route: route.fulfill(json={"messages": [], "latest_seq": 0}),
    )
    page.route(
        "**/api/needs-you-count",
        lambda route: route.fulfill(json={"needs_you_count": 1}),
    )
    page.route("**/api/degraded", lambda route: route.fulfill(json={"sources": []}))
    page.route(
        "**/api/mailbox/request-1",
        lambda route: route.fulfill(
            json={
                "msg_id": "request-1",
                "kind": "permission",
                "type": "approval",
                "mailbox_open": True,
                "sender": "varde-builder",
                "title": "Needs approval",
                "state": "pending",
                "asked": "Run command: /bin/zsh -lc 'git status'",
                "body": "Builder requests permission to run git status.",
                "options": [
                    {"id": "allow", "label": "Allow"},
                    {"id": "deny", "label": "Deny"},
                ],
            }
        ),
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/")
    page.locator(".chat-list main .chat-row").filter(
        has_text="Builder wants to run: git status"
    ).wait_for()
    assert page.get_by_text("Worker", exact=True).count() == 0
    assert page.get_by_text("All caught up").count() == 0
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator(".chat-list main .chat-row").filter(
        has_text="Builder wants to run: git status"
    ).click()
    page.wait_for_url("**/threads/sender%3Avarde-builder")
    page.get_by_text("Builder requests permission to run git status.").wait_for()
    page.get_by_role("button", name="Allow").wait_for()


def test_failed_pin_save_restores_last_saved_state(browser_page):
    page, _, _, origin, _ = browser_page
    page.route(
        "**/api/instance-threads**",
        lambda route: route.fulfill(
            json={
                "threads": [
                    {
                        "thread_key": "instance:builder",
                        "agent_id": "builder",
                        "role": "builder",
                        "label": "Builder",
                        "state": "running",
                        "last_activity": "2026-10-27T10:00:00Z",
                    }
                ]
            }
        ),
    )

    def pins_route(route):
        if route.request.method == "PUT":
            route.fulfill(status=500, json={"error": "storage unavailable"})
        else:
            route.fulfill(json={"pins": ["builder"]})

    page.route("**/api/pins", pins_route)
    page.add_init_script("""
      const originalFetch = window.fetch.bind(window);
      window.fetch = (input, init = {}) => {
        const url = typeof input === 'string' ? input : input.url;
        if (url.endsWith('/api/pins') && init.method === 'PUT') {
          return Promise.resolve(
            new Response('{"error":"storage unavailable"}', {status: 500})
          );
        }
        return originalFetch(input, init);
      };
    """)
    page.route("**/api/threads", lambda route: route.fulfill(json=[]))
    page.route("**/api/mailbox?**", lambda route: route.fulfill(json={"items": []}))
    page.route("**/api/agents", lambda route: route.fulfill(json=[]))
    page.route(
        "**/api/chat?thread=main**",
        lambda route: route.fulfill(json={"messages": [], "latest_seq": 0}),
    )
    page.route(
        "**/api/needs-you-count",
        lambda route: route.fulfill(json={"needs_you_count": 0}),
    )
    page.route("**/api/degraded", lambda route: route.fulfill(json={"sources": []}))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/")
    page.locator(".chat-list .pin-heading button").click()
    page.get_by_role("button", name="Unpin Builder").click()
    page.get_by_role("alert").get_by_text(
        "Could not save pinned conversations."
    ).wait_for()
    page.locator(".bubbles .bubble-wrap").filter(
        has=page.get_by_role("link", name="Builder")
    ).wait_for()
    assert (
        page.locator(".chat-list main .chat-row").filter(has_text="Builder").count()
        == 0
    )


def test_chat_list_desktop_has_no_horizontal_overflow(browser_page):
    page, _, _, origin, _ = browser_page
    page.route(
        "**/api/threads",
        lambda route: route.fulfill(
            json=[
                {
                    "thread_id": "sender:empty",
                    "sender": "varde-builder",
                    "title": "Builder",
                    "open_count": 0,
                    "stale_count": 0,
                    "last_ts": "2026-10-27T10:00:00Z",
                    "last_preview": "",
                    "decision_ids": [],
                }
            ]
        ),
    )
    page.route("**/api/mailbox?**", lambda route: route.fulfill(json={"items": []}))
    page.route("**/api/agents", lambda route: route.fulfill(json=[]))
    page.route(
        "**/api/instance-threads**", lambda route: route.fulfill(json={"threads": []})
    )
    page.route(
        "**/api/chat?thread=main**",
        lambda route: route.fulfill(json={"messages": [], "latest_seq": 0}),
    )
    page.route("**/api/degraded", lambda route: route.fulfill(json={"sources": []}))
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{origin}/")
    page.locator(".desktop-chat-sidebar").get_by_text("No conversations yet").wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_chat_shell_has_no_horizontal_scrolling(browser_page):
    page, _, _, origin, _ = browser_page
    shots_dir = os.environ.get("VARDE_SHOTS_DIR")
    page.route(
        "**/api/threads",
        lambda route: route.fulfill(
            json=[
                {
                    "thread_id": "sender:empty",
                    "sender": "varde-builder",
                    "title": "Builder",
                    "open_count": 0,
                    "stale_count": 0,
                    "last_ts": "2026-10-27T10:00:00Z",
                    "last_preview": "",
                    "decision_ids": [],
                }
            ]
        ),
    )
    page.route("**/api/mailbox?**", lambda route: route.fulfill(json={"items": []}))
    page.route("**/api/agents", lambda route: route.fulfill(json=[]))
    page.route(
        "**/api/instance-threads**",
        lambda route: route.fulfill(
            json={
                "threads": [
                    {
                        "thread_key": "instance:builder",
                        "agent_id": "builder",
                        "role": "builder",
                        "label": "Builder",
                        "state": "running",
                        "last_activity": "2099-10-27T10:00:00Z",
                    }
                ]
            }
        ),
    )
    page.route(
        "**/api/chat?thread=main**",
        lambda route: route.fulfill(json={"messages": [], "latest_seq": 0}),
    )
    page.route(
        "**/api/chat?thread=instance%3Abuilder**",
        lambda route: route.fulfill(
            json={
                "messages": [],
                "latest_seq": 0,
                "thread": {
                    "key": "instance:builder",
                    "kind": "instance",
                    "label": "Builder",
                    "state": "running",
                },
                "bot": {"state": "unavailable", "context_pct": None, "generation": 0},
            }
        ),
    )
    page.route(
        "**/api/chat/stream?**",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.route(
        "**/api/needs-you-count",
        lambda route: route.fulfill(json={"needs_you_count": 0}),
    )
    page.route("**/api/degraded", lambda route: route.fulfill(json={"sources": []}))

    def assert_no_horizontal_scrolling():
        violations = page.evaluate("""() => {
          const doc = document.documentElement;
          const bad = [...document.querySelectorAll('*')].filter(el => {
            const overflow = getComputedStyle(el).overflowX;
            return (overflow === 'auto' || overflow === 'scroll') &&
              el.scrollWidth > el.clientWidth + 1;
          }).map(el => `${el.tagName}.${el.className}`);
          return {document: [doc.scrollWidth, doc.clientWidth], bad};
        }""")
        assert violations["document"][0] <= violations["document"][1] + 1, violations
        assert not violations["bad"], violations

    for width in (390, 1280):
        page.set_viewport_size({"width": width, "height": 844})
        for theme in ("light", "dark"):
            page.emulate_media(color_scheme=theme)
            page.goto(f"{origin}/")
            if width < 900:
                page.locator(".pin-heading button:visible").wait_for()
            else:
                page.locator(".desktop-chat-sidebar").wait_for()
            page.evaluate(
                "theme => document.documentElement.dataset.theme = theme", theme
            )
            assert_no_horizontal_scrolling()
            if width < 900:
                page.locator(".pin-heading button:visible").click()
                page.get_by_role("button", name="Add").click()
                assert_no_horizontal_scrolling()
                page.goto(f"{origin}/chat/needs")
            else:
                page.locator(".desktop-chat-sidebar .pin-heading button").click()
                page.get_by_role("button", name="Add a pinned conversation").click()
                assert_no_horizontal_scrolling()
                page.goto(f"{origin}/chat/needs")
            page.get_by_role("heading", name="Needs action").wait_for()
            page.evaluate(
                "theme => document.documentElement.dataset.theme = theme", theme
            )
            assert_no_horizontal_scrolling()
            if width == 390 and theme == "light" and shots_dir:
                page.screenshot(path=f"{shots_dir}/needs-390.png", full_page=True)
            page.goto(f"{origin}/thread/builder")
            page.locator(".chat-thread").wait_for()
            page.evaluate(
                "theme => document.documentElement.dataset.theme = theme", theme
            )
            assert_no_horizontal_scrolling()
            if width == 390 and theme == "light" and shots_dir:
                page.screenshot(path=f"{shots_dir}/thread-390.png", full_page=True)
            if width < 900:
                page.goto(f"{origin}/")
                page.locator(".pin-heading button:visible").wait_for()
                page.evaluate(
                    "theme => document.documentElement.dataset.theme = theme", theme
                )
                page.get_by_role("button", name="Open menu").click()
                assert_no_horizontal_scrolling()
