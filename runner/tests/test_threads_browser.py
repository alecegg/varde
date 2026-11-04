from __future__ import annotations

import pytest
import test_web_browser
from playwright.sync_api import expect
from test_agents_page_browser import agent_browser  # noqa: F401
from varde_runner.waits import approval_wait_id

pytestmark = pytest.mark.slow

pytest_plugins = ["test_agents_page_browser"]
browser_page = test_web_browser.browser_page


@pytest.fixture
def clean_agent_browser(agent_browser):  # noqa: F811
    yield agent_browser
    agent_browser[0].unroute_all(behavior="ignoreErrors")


def install_empty_chat_routes(page, thread_key, label):
    page.route(
        "**/api/chat/stream**",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.route(
        "**/api/chat?**",
        lambda route: route.fulfill(
            json={
                "messages": [],
                "latest_seq": 0,
                "thread": {
                    "key": thread_key,
                    "kind": "instance",
                    "label": label,
                    "state": "running",
                },
                "bot": {"state": "idle", "context_pct": None, "generation": 0},
            }
        ),
    )


def test_thread_detail_hides_agent_to_agent_mail(browser_page):
    page, _, _, origin, _ = browser_page
    page.route(
        "**/api/threads",
        lambda route: route.fulfill(
            json=[
                {
                    "thread_id": "sender:builder-1",
                    "plan_id": None,
                    "sender": "Builder 1",
                    "title": "Build update",
                    "open_count": 0,
                    "last_ts": "2026-10-27T00:00:00Z",
                    "last_preview": "Done",
                    "decision_ids": ["internal-note"],
                }
            ]
        ),
    )
    page.route(
        "**/api/mailbox?**",
        lambda route: route.fulfill(
            json={
                "items": [{"msg_id": "internal-note", "kind": "info", "to": "reviewer"}]
            }
        ),
    )
    page.route(
        "**/api/mailbox/internal-note",
        lambda route: route.fulfill(
            json={
                "msg_id": "internal-note",
                "kind": "info",
                "to": "reviewer",
                "body": "Private worker note",
            }
        ),
    )
    page.goto(f"{origin}/threads/sender%3Abuilder-1")
    expect(page.get_by_role("heading", name="Builder 1", exact=True)).to_be_visible()
    expect(page.get_by_text("Done", exact=True)).to_be_visible()
    expect(page.get_by_text("Private worker note")).to_have_count(0)


def test_sender_thread_shows_user_facing_requests(browser_page):
    page, _, _, origin, _ = browser_page
    message = {
        "msg_id": "decision-1",
        "kind": "permission",
        "type": "approval",
        "state": "pending",
        "ts": "2026-10-27T10:00:00Z",
        "sender": "varde-builder",
        "agent_title": "Builder",
        "title": "Run command: /bin/zsh -lc 'git status'",
        "asked": "Run command: /bin/zsh -lc 'git status'",
        "body": "Builder requests permission to run git status.",
        "options": [{"id": "allow", "label": "Allow"}, {"id": "deny", "label": "Deny"}],
        "mailbox_open": True,
    }
    page.route(
        "**/api/threads",
        lambda route: route.fulfill(
            json=[
                {
                    "thread_id": "sender:builder-uuid",
                    "plan_id": None,
                    "sender": "varde-builder",
                    "title": message["title"],
                    "open_count": 1,
                    "last_ts": message["ts"],
                    "last_preview": message["body"],
                    "decision_ids": ["decision-1"],
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
                        key: message[key]
                        for key in (
                            "msg_id",
                            "kind",
                            "type",
                            "state",
                            "ts",
                            "sender",
                            "title",
                            "asked",
                        )
                    }
                    | {"mailbox_open": True, "summary_only": True}
                ]
            }
        ),
    )
    page.route("**/api/mailbox/decision-1", lambda route: route.fulfill(json=message))

    page.goto(f"{origin}/threads/sender%3Abuilder-uuid")
    expect(
        page.get_by_role("heading", name="Builder", exact=True).first
    ).to_be_visible()
    expect(
        page.locator(".page").get_by_text("Builder wants to run: git status").first
    ).to_be_visible()
    expect(
        page.locator(".page").get_by_role(
            "heading", name="Builder wants to run: git status"
        )
    ).to_be_visible()
    expect(
        page.locator(".page").get_by_text(
            "Builder requests permission to run git status."
        )
    ).to_be_visible()
    expect(page.get_by_role("button", name="Allow")).to_be_visible()

    page.route(
        "**/api/threads",
        lambda route: route.fulfill(
            json=[
                {
                    "thread_id": "sender:empty-uuid",
                    "plan_id": None,
                    "sender": "varde-builder",
                    "title": "No messages",
                    "open_count": 0,
                    "last_ts": "2026-10-27T10:00:00Z",
                    "last_preview": "",
                    "decision_ids": [],
                }
            ]
        ),
    )
    page.goto(f"{origin}/threads/sender%3Aempty-uuid")
    expect(page.get_by_role("heading", name="Builder", exact=True)).to_be_visible()
    expect(page.locator(".empty-thread")).to_have_text("No messages")
    expect(page.get_by_role("alert")).to_have_count(0)


def test_instance_thread_uses_role_composer_without_queue_card(browser_page):
    page, _, _, origin, _ = browser_page
    install_empty_chat_routes(page, "instance:builder-1", "Builder 1")
    page.route(
        "**/api/instance-threads?agent=builder-1",
        lambda route: route.fulfill(
            json={
                "threads": [
                    {
                        "thread_key": "instance:builder-1",
                        "agent_id": "builder-1",
                        "plan_id": None,
                        "role": "builder",
                        "label": "Builder 1",
                        "state": "running",
                        "last_activity": None,
                    }
                ]
            }
        ),
    )
    page.goto(f"{origin}/thread/builder-1")

    composer = page.get_by_role("textbox", name="Message Builder")
    composer.wait_for()
    assert composer.is_enabled()
    assert page.get_by_text("Working on Build the shell, 2 in queue").count() == 0
    assert page.get_by_role("button", name="Take over").count() == 0


def _launch_thread_agent(page, origin, workspace):
    response = page.request.post(
        f"{origin}/api/agents",
        data={
            "harness": "claude_cli",
            "workspace": str(workspace),
            "role": "builder",
            "prompt": "start t10 thread browser test",
        },
    )
    assert response.ok, response.text()
    agent_id = response.json()["agent_id"]
    page.goto(f"{origin}/thread/{agent_id}")
    return agent_id


def test_instance_thread_handoff_reply_and_unread_scope(clean_agent_browser):
    page, origin, supervisor, plugin, workspace, _ = clean_agent_browser
    agent_id = _launch_thread_agent(page, origin, workspace)
    session = supervisor.resolve_session(agent_id)
    assert session
    key = f"instance:{agent_id}"
    request_id = "t9-browser-question"
    supervisor.store.create_wait(
        approval_wait_id(session["id"], request_id),
        session["id"],
        "approval",
        payload={"request_id": request_id, "summary": "Should the handoff continue?"},
    )
    handoff_row = {
        "seq": 1,
        "change_seq": 1,
        "id": "handoff-row",
        "thread_key": key,
        "reply_to": None,
        "role": "event",
        "kind": "handoff",
        "text": "Summary: continue the browser tests",
        "link": "/notes/HANDOFF.md",
        "state": "sent",
        "source_agent_id": agent_id,
        "source_event_seq": 1,
        "created_at": "2026-10-26T00:00:00Z",
    }
    question = {
        **handoff_row,
        "seq": 2,
        "change_seq": 2,
        "id": "question-row",
        "kind": "question",
        "text": "Should the handoff continue?",
        "link": f"/api/agents/{agent_id}/respond?request_id={request_id}",
        "source_event_seq": 2,
    }

    def history(route):
        if "thread=main" in route.request.url:
            route.fulfill(
                json={
                    "messages": [],
                    "latest_seq": 0,
                    "thread": {
                        "key": "main",
                        "kind": "main",
                        "label": "Chat",
                        "state": "idle",
                    },
                    "bot": {"state": "idle", "context_pct": None, "generation": 0},
                }
            )
            return
        route.fulfill(
            json={
                "messages": [handoff_row, question],
                "latest_seq": 2,
                "thread": {
                    "key": key,
                    "kind": "instance",
                    "label": "Browser builder",
                    "state": "idle",
                },
                "bot": {"state": "idle", "context_pct": None, "generation": 0},
            }
        )

    page.route("**/api/chat?*", history)
    page.route("**/api/chat/stream?*", lambda route: route.abort())
    sent = []

    def capture_send(route):
        sent.append(route.request.post_data_json)
        route.fulfill(json={"id": "reply-row", "seq": 2}, status=202)

    page.route("**/api/chat/messages", capture_send)
    page.goto(f"{origin}/thread/{agent_id}")

    handoff_link = page.get_by_role("link", name="Summary: continue the browser tests")
    handoff_link.wait_for()
    assert handoff_link.get_attribute("href") == "/notes/HANDOFF.md"
    assert page.get_by_text("Context: private handoff details").count() == 0
    assert page.locator(".unread-dot").count() == 0
    composer = page.get_by_role("textbox", name="Message Builder")
    assert composer.count() == 1
    assert composer.is_enabled()
    assert page.get_by_label("Recipient").count() == 0

    with page.expect_response("**/api/agents/*/respond"):
        page.get_by_role("button", name="Allow").click()
    assert plugin.responses == [(request_id, "allow")]

    composer.fill("Please continue")
    with page.expect_response("**/api/chat/messages"):
        page.get_by_role("button", name="Send").click()
    assert len(sent) == 1
    assert sent[0]["thread"] == key
    assert sent[0]["reply_to"] is None
    page.evaluate(
        """async ({thread}) => {
          await fetch('/api/chat/messages', {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify({
              client_msg_id: 'reply-to-message', text: 'Follow up', thread,
              reply_to: 'handoff-row'
            })
          });
        }""",
        {"thread": key},
    )
    assert sent[1]["thread"] == key
    assert sent[1]["reply_to"] == "handoff-row"

    page.route(
        "**/api/instance-threads",
        lambda route: route.fulfill(
            json={
                "threads": [
                    {
                        "thread_key": key,
                        "agent_id": agent_id,
                        "plan_id": "plan-with-worker",
                        "role": "builder",
                        "label": "Browser builder",
                        "state": "idle",
                        "last_activity": None,
                    }
                ]
            }
        ),
    )
    page.goto(f"{origin}/agents")
    expect(page.locator("article.agent h2", has_text=agent_id)).to_have_count(0)
    page.goto(origin)
    assert page.get_by_text(agent_id, exact=True).count() == 0


def test_plan_task_links_to_its_worker_thread(browser_page):
    page, _, _, origin, _ = browser_page
    plan_id = "2026-10-25-chat-threads"
    page.route(
        f"**/api/plans/{plan_id}",
        lambda route: route.fulfill(
            json={
                "id": plan_id,
                "title": "Chat threads",
                "status": "running",
                "plan_text": "Plan",
                "tasks": [
                    {
                        "id": "T9",
                        "title": "Integrate docs",
                        "status": "todo",
                        "acceptance_criteria": [],
                    }
                ],
                "notes_status": "present",
                "review_status": "pending",
                "comments": [],
            }
        ),
    )
    page.route(
        f"**/api/plans/{plan_id}/task-queue",
        lambda route: route.fulfill(json={"items": [], "role_sessions": []}),
    )
    worker = {
        "thread_key": "instance:worker-9",
        "agent_id": "worker-9",
        "plan_id": plan_id,
        "role": "builder",
        "label": "T9 builder",
        "state": "running",
        "last_activity": "just now",
    }
    page.route(
        f"**/api/instance-threads?plan={plan_id}",
        lambda route: route.fulfill(json={"threads": [worker]}),
    )
    page.route(
        "**/api/instance-threads?agent=worker-9",
        lambda route: route.fulfill(json={"threads": [worker]}),
    )
    install_empty_chat_routes(page, "instance:worker-9", "T9 builder")
    page.route(
        "**/api/agents",
        lambda route: route.fulfill(
            json=[{"agent_id": "worker-9", "workspace": "worktree/T9"}]
        ),
    )

    page.goto(f"{origin}/plans/{plan_id}")
    task_link = page.locator("a.instance").filter(has_text="T9 builder")
    task_link.wait_for()
    assert task_link.get_attribute("href") == "/thread/worker-9"
    task_link.click()
    page.get_by_role("heading", name="T9 builder").wait_for()
