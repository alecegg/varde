from __future__ import annotations

import pytest
import test_web_browser

pytestmark = pytest.mark.slow

browser_page = test_web_browser.browser_page


@pytest.fixture(autouse=True)
def browser_errors_fail(request, browser_page):
    """Make browser errors and failed app requests fail each test in this module."""
    page = browser_page[0]
    page.route(
        "**/api/instance-threads**",
        lambda route: route.fulfill(
            json={
                "threads": [
                    {
                        "thread_key": "instance:builder",
                        "agent_id": "builder",
                        "plan_id": None,
                        "role": "builder",
                        "label": "Builder",
                        "state": "running",
                        "last_activity": "2026-10-27T09:00:00Z",
                    }
                ]
            }
        ),
    )
    page.route("**/api/pins", lambda route: route.fulfill(json={"pins": []}))
    errors = []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "requestfailed",
        lambda request: (
            errors.append(f"{request.method} {request.url}: {request.failure}")
            if request.failure and "ERR_ABORTED" not in request.failure
            else None
        ),
    )
    yield
    assert not errors, "Browser errors or failed requests:\n" + "\n".join(errors)


def home_summary(*, role="builder", needs_you=0):
    return {
        "role": role,
        "state": "needs_you" if needs_you else "running",
        "queued": 1,
        "needs_you": needs_you,
        "current": "Implement chat shell",
    }


def test_needs_chat_route_loads_the_built_static_app(browser_page):
    page, _, _, origin, _ = browser_page
    page.route("**/api/threads", lambda route: route.fulfill(json=[]))
    page.route("**/api/agents", lambda route: route.fulfill(json=[]))

    page.goto(f"{origin}/chat/needs")

    page.get_by_role("heading", name="Needs action").wait_for()
    page.get_by_role("region", name="Needs action").get_by_text(
        "All caught up"
    ).wait_for()


def test_needs_action_badge_matches_real_open_plan_and_agent_items(browser_page):
    page, _, _, origin, cli = browser_page
    cli.messages = [
        {
            "id": "plan-open",
            "from": "plan-1",
            "kind": "needs-user",
            "text": "Review the plan",
        },
        {
            "id": "plan-stale",
            "from": "plan-1",
            "kind": "needs-user",
            "text": "Resolved request",
        },
    ]
    cli.message_status = {
        "messages": [{"id": "plan-stale", "acked": "2026-10-28T12:00:00Z"}]
    }
    test_web_browser.reproject_messages(cli.dashboard_app)
    page.unroute("**/api/mailbox/*")
    page.route(
        "**/api/agents",
        lambda route: route.fulfill(
            json=[
                {
                    "agent_id": "builder-1",
                    "harness": "test",
                    "role": "builder",
                    "workspace": None,
                    "lifecycle": "running",
                    "idle_status": None,
                    "capabilities": {"respond": True},
                    "pending_requests": [
                        {
                            "request_id": "permission-1",
                            "kind": "permission",
                            "summary": "Allow the live request?",
                        }
                    ],
                }
            ]
        ),
    )
    page.goto(f"{origin}/")

    page.locator(".pin-section .needs-action .badge").get_by_text(
        "2", exact=True
    ).wait_for()
    page.locator(".pin-section .needs-action").click()
    cards = page.locator("[data-answer-card]")
    cards.filter(has_text="Review the plan").wait_for()
    page.get_by_text("Allow the live request?", exact=True).wait_for()
    assert cards.count() == 2
    assert not cards.filter(has_text="Resolved request").count()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_edit_pins_moves_thread_out_of_regular_list_and_saves(browser_page):
    page, _, _, origin, _ = browser_page
    rows = [
        {**home_summary(role="manager-bot"), "agent_id": "manager"},
        {**home_summary(role="builder"), "agent_id": "builder"},
    ]
    saved_pins = []
    page.route("**/api/home", lambda route: route.fulfill(json={"roles": rows}))
    page.route("**/api/agents", lambda route: route.fulfill(json=[]))
    page.route(
        "**/api/needs-you-count",
        lambda route: route.fulfill(json={"needs_you_count": 0}),
    )

    def pins(route):
        nonlocal saved_pins
        if route.request.method == "PUT":
            saved_pins = route.request.post_data_json["pins"]
        route.fulfill(json={"pins": saved_pins})

    page.route("**/api/pins", pins)
    page.goto(f"{origin}/")
    row = page.get_by_role("link", name="Builder Active now")
    row.wait_for()
    page.get_by_role("button", name="Edit").click()
    page.locator(".bubble.add").click()
    page.get_by_role("button", name="Pin Builder").click()
    page.locator(".bubble-wrap .bubble[href='/thread/builder']").wait_for()
    assert page.locator(".chat-row[href='/thread/builder']").count() == 0
    assert saved_pins == ["builder"]


def test_chat_list_links_to_registered_session_and_loads_its_transcript(browser_page):
    page, _, _, origin, _ = browser_page
    page.route(
        "**/api/chat?**",
        lambda route: route.fulfill(
            json={
                "messages": [
                    {
                        "id": "builder-message",
                        "seq": 1,
                        "change_seq": 1,
                        "thread_key": "instance:builder",
                        "role": "bot",
                        "kind": "message",
                        "text": "Builder session transcript is available.",
                        "link": None,
                        "state": "sent",
                        "reply_to": None,
                        "source_agent_id": "builder",
                        "source_event_seq": 1,
                        "created_at": "2026-10-27T09:00:00Z",
                    }
                ],
                "latest_seq": 1,
                "thread": {
                    "key": "instance:builder",
                    "kind": "instance",
                    "label": "Builder",
                    "state": "running",
                },
                "bot": {"state": "idle", "context_pct": None, "generation": 0},
            }
        ),
    )
    page.route(
        "**/api/chat/stream**",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.goto(f"{origin}/")
    page.get_by_role("link", name="Builder Active now").click()
    page.get_by_text("Builder session transcript is available.").wait_for()
    assert page.url.endswith("/thread/builder")


def test_thread_uses_flex_height_readable_label_and_in_flow_composer(browser_page):
    page, _, _, origin, _ = browser_page
    page.route(
        "**/api/instance-threads?agent=reviewer-guid",
        lambda route: route.fulfill(
            json={
                "threads": [
                    {
                        "thread_key": "instance:reviewer-guid",
                        "agent_id": "reviewer-guid",
                        "plan_id": None,
                        "role": "reviewer",
                        "label": "Reviewer",
                        "state": "running",
                        "last_activity": "2026-10-28T10:00:00Z",
                    }
                ]
            }
        ),
    )
    page.route(
        "**/api/chat?**",
        lambda route: route.fulfill(
            json={
                "messages": [
                    {
                        "id": f"event-{index}",
                        "seq": index,
                        "change_seq": index,
                        "thread_key": "instance:reviewer-guid",
                        "role": "event",
                        "kind": "tool",
                        "text": text,
                        "link": None,
                        "state": "sent",
                        "reply_to": None,
                        "source_agent_id": "reviewer-guid",
                        "source_event_seq": index,
                        "created_at": "2026-10-28T10:00:00Z",
                    }
                    for index, text in enumerate(
                        [
                            "Bash: running",
                            "tool: completed",
                            "Read: running",
                            "tool: failed",
                        ],
                        start=1,
                    )
                ],
                "latest_seq": 4,
                "thread": {
                    "key": "instance:reviewer-guid",
                    "kind": "instance",
                    "label": "Reviewer",
                    "state": "running",
                },
                "bot": {"state": "idle", "context_pct": None, "generation": 0},
            }
        ),
    )
    page.route(
        "**/api/chat/stream**",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.route(
        "**/api/queue/roles/reviewer",
        lambda route: route.fulfill(json={"summary": None}),
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.emulate_media(color_scheme="dark")
    page.goto(f"{origin}/thread/reviewer-guid")
    assert page.get_by_text("Bash: running", exact=True).count() == 0
    assert page.get_by_text("tool: completed", exact=True).count() == 0
    heading = page.get_by_role("heading", name="Reviewer")
    heading.wait_for()
    assert heading.count() == 1
    back = page.get_by_role("link", name="Back to chats")
    assert back.get_attribute("href") == "/chat"
    assert page.locator("[data-profile-link]").count() == 0
    composer = page.get_by_role("textbox", name="Message Reviewer")
    composer.wait_for()
    assert composer.get_attribute("placeholder") == "Message Reviewer"
    viewport_content = page.locator('meta[name="viewport"]').get_attribute("content")
    assert "interactive-widget=resizes-content" in viewport_content
    assert (
        page.evaluate("""() => {
      document.documentElement.style.setProperty('--thread-viewport-height', '500px');
      const shell = document.querySelector('.chat-shell');
      const height = shell.getBoundingClientRect().height;
      document.documentElement.style.removeProperty('--thread-viewport-height');
      return height;
    }""")
        == 500
    )
    geometry = page.evaluate("""() => {
      const messages = document.querySelector('.messages').getBoundingClientRect();
      const composer = document.querySelector('.composer').getBoundingClientRect();
      const textarea = document.querySelector('.composer textarea')
        .getBoundingClientRect();
      const statuses = [...document.querySelectorAll('.event-row')]
        .map(node => node.getBoundingClientRect());
      const card = document.querySelector('[data-pinned-content]')
        ?.getBoundingClientRect();
      return {
        messages, composer, textarea, statuses, card,
        height: innerHeight, width: innerWidth,
        scrollWidth: document.documentElement.scrollWidth
      };
    }""")
    assert geometry["messages"]["height"] > 0
    assert geometry["composer"]["bottom"] <= geometry["height"]
    assert geometry["textarea"]["height"] == 48
    composer.click()
    page.set_viewport_size({"width": 390, "height": 508})
    page.wait_for_timeout(100)
    keyboard_geometry = page.evaluate("""() => {
      const header = document.querySelector('.app-header').getBoundingClientRect();
      const composer = document.querySelector('.composer').getBoundingClientRect();
      const messages = document.querySelector('.messages');
      const longContent = document.createElement('div');
      longContent.style.height = '1200px';
      longContent.style.flex = 'none';
      messages.append(longContent);
      messages.scrollTop = 0;
      const initial = messages.scrollTop;
      messages.scrollTop = messages.scrollHeight;
      return { header, composer, height: innerHeight,
        scrolls: messages.scrollHeight > messages.clientHeight
          && messages.scrollTop > initial };
    }""")
    assert keyboard_geometry["header"]["top"] >= 0
    assert keyboard_geometry["header"]["bottom"] < 508
    assert keyboard_geometry["composer"]["bottom"] <= 508
    assert keyboard_geometry["scrolls"]
    assert all(
        row["top"] >= geometry["messages"]["top"]
        and row["bottom"] <= geometry["messages"]["bottom"]
        for row in geometry["statuses"]
    )
    if geometry["card"]:
        assert geometry["card"]["bottom"] <= geometry["composer"]["top"]
    assert geometry["scrollWidth"] <= geometry["width"]
    for width in (390, 1280):
        for scheme in ("light", "dark"):
            page.set_viewport_size({"width": width, "height": 844})
            page.emulate_media(color_scheme=scheme)
            assert page.evaluate(
                """() => document.documentElement.scrollWidth
                  <= document.documentElement.clientWidth"""
            )


def test_manager_disabled_notice_and_composer(browser_page):
    page, _, _, origin, _ = browser_page
    page.route(
        "**/api/home", lambda route: route.fulfill(json={"roles": [home_summary()]})
    )
    page.route(
        "**/api/roles",
        lambda route: route.fulfill(
            json={"roles": {"manager-bot": {"enabled": False}}}
        ),
    )
    page.goto(f"{origin}/thread/manager")

    notice = page.locator(".manager-off-state")
    notice.wait_for()
    assert notice.get_by_role(
        "heading", name="Start a manager conversation"
    ).is_visible()
    assert "Manager bot is off. Start it to chat." in notice.inner_text()
    assert page.get_by_role("textbox", name="Message").count() == 0
    settings_link = notice.get_by_role("link", name="Start")
    assert settings_link.get_attribute("href") == "/settings"


def test_two_pending_requests_on_one_agent_count_on_chip_and_needs_list(browser_page):
    page, _, _, origin, _ = browser_page
    page.route(
        "**/api/home",
        lambda route: route.fulfill(json={"roles": [home_summary(needs_you=2)]}),
    )
    page.route(
        "**/api/needs-you-count",
        lambda route: route.fulfill(json={"needs_you_count": 2}),
    )
    page.route(
        "**/api/roles",
        lambda route: route.fulfill(json={"roles": {"manager-bot": {"enabled": True}}}),
    )
    page.route(
        "**/api/agents",
        lambda route: route.fulfill(
            json=[
                {
                    "agent_id": "builder-1",
                    "harness": "claude_cli",
                    "role": "builder",
                    "workspace": None,
                    "lifecycle": "running",
                    "idle_status": None,
                    "capabilities": {"respond": True},
                    "pending_requests": [
                        {
                            "request_id": "approval-1",
                            "kind": "approval",
                            "summary": "Allow first action?",
                        },
                        {
                            "request_id": "approval-2",
                            "kind": "approval",
                            "summary": "Allow second action?",
                        },
                    ],
                }
            ]
        ),
    )
    page.goto(f"{origin}/")

    page.locator(".pin-section .needs-action .badge").get_by_text(
        "2", exact=True
    ).wait_for()
    page.locator(".pin-section .needs-action").click()
    page.get_by_text("Allow first action?", exact=True).wait_for()
    page.get_by_text("Allow second action?", exact=True).wait_for()
    assert page.locator("[data-answer-card]").count() == 2


@pytest.mark.parametrize(
    ("decision", "label"), [("allow", "Approved"), ("deny", "Denied")]
)
def test_needs_you_answer_shows_visible_resolution(browser_page, decision, label):
    page, _, _, origin, _ = browser_page
    page.route(
        "**/api/home",
        lambda route: route.fulfill(json={"roles": [home_summary(needs_you=1)]}),
    )
    page.route(
        "**/api/needs-you-count",
        lambda route: route.fulfill(json={"needs_you_count": 1}),
    )
    page.route(
        "**/api/roles",
        lambda route: route.fulfill(json={"roles": {"manager-bot": {"enabled": True}}}),
    )
    page.route(
        "**/api/agents",
        lambda route: route.fulfill(
            json=[
                {
                    "agent_id": "builder-1",
                    "harness": "claude_cli",
                    "role": "builder",
                    "workspace": None,
                    "lifecycle": "running",
                    "idle_status": None,
                    "capabilities": {"respond": True},
                    "pending_requests": [
                        {
                            "request_id": "approval-1",
                            "kind": "approval",
                            "summary": "Allow the deployment?",
                        }
                    ],
                }
            ]
        ),
    )
    page.route(
        "**/api/agents/builder-1/watch?*",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body="event: ready\ndata: {}\n\n",
        ),
    )
    answers = []

    def respond(route):
        answers.append(route.request.post_data_json)
        route.fulfill(json={"result": "ok"})

    page.route("**/api/agents/builder-1/respond", respond)
    page.goto(f"{origin}/")
    page.locator(".pin-section .needs-action").click()
    card = page.locator("[data-answer-card]").filter(has_text="Allow the deployment?")
    card.get_by_role("button", name="Allow" if decision == "allow" else "Deny").click()
    card.get_by_role("status").get_by_text(label, exact=True).wait_for()
    assert answers[0]["decision"] == decision


def test_chat_header_back_opens_chat_list(browser_page):
    page, _, _, origin, _ = browser_page
    page.route(
        "**/api/instance-threads**",
        lambda route: route.fulfill(
            json={
                "threads": [
                    {
                        "thread_key": "instance:builder",
                        "agent_id": "builder",
                        "plan_id": None,
                        "role": "builder",
                        "label": "Builder",
                        "state": "running",
                        "last_activity": "2026-10-28T10:00:00Z",
                    }
                ]
            }
        ),
    )
    page.route("**/api/agents", lambda route: route.fulfill(json=[]))
    page.route(
        "**/api/chat?thread=main**",
        lambda route: route.fulfill(
            json={"messages": [], "latest_seq": 0, "thread": {}, "bot": {}}
        ),
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/thread/manager")
    page.get_by_role("link", name="Back to chats").click()
    page.wait_for_url("**/chat")
    page.get_by_role("heading", name="Chats").wait_for()
    page.locator(".chat-row").first.wait_for()
    assert page.locator(".chat-row").count() >= 1
    assert page.get_by_role("button", name="Search").count() == 0
    assert (
        page.get_by_role("button", name="Edit").evaluate(
            "element => element.getBoundingClientRect().height"
        )
        >= 44
    )
