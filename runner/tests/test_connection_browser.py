from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import test_web_browser

pytestmark = pytest.mark.slow

browser_page = test_web_browser.browser_page

CONNECTION_TS = Path(__file__).parents[1] / "ui" / "src" / "lib" / "connection.ts"
SHOTS = Path(
    "/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-20-dashboard-queue/notes/shots"
)

FAKE_EVENT_SOURCE = """
window.__skew = 0;
const realNow = Date.now.bind(Date);
Date.now = () => realNow() + window.__skew;
window.__sources = [];
window.EventSource = class {
  constructor() {
    window.__sources.push(this);
    setTimeout(() => this.onopen && this.onopen(), 0);
  }
  addEventListener() {}
  close() {}
};
"""

STATE_MACHINE_SCRIPT = """
import { initialConnection, nextConnection, connectionLabel } from './connection.ts';
let s = initialConnection(0);
const out = [];
const step = (e, t) => {
  s = nextConnection(s, e, t);
  out.push(`${s.status}:${connectionLabel(s, t)}`);
};
step('tick', 1000); step('open', 2000); step('tick', 3000); step('error', 4000);
step('tick', 8999); step('tick', 9000); step('tick', 34000); step('tick', 40000);
step('error', 41000); step('open', 42000);
console.log(out.join('|'));
"""


def test_connection_state_machine():
    result = subprocess.run(  # noqa: S603 - Test runs the browser state fixture in Node with controlled input.
        ["node", "--input-type=module", "-e", STATE_MACHINE_SCRIPT],  # noqa: S607 - Test resolves the installed Node runtime from PATH.
        cwd=CONNECTION_TS.parent,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip().split("|") == [
        "connecting:",
        "healthy:",
        "healthy:",
        "reconnecting:",
        "reconnecting:",
        "stale:Connection lost. Some updates may be delayed.",
        "stale:Connection lost. Some updates may be delayed.",
        "stale:Connection lost. Some updates may be delayed.",
        "stale:Connection lost. Some updates may be delayed.",
        "healthy:",
    ]


def test_indicator_reconnecting_then_stale(browser_page):
    page, _, _, origin, _ = browser_page
    page.add_init_script(FAKE_EVENT_SOURCE)
    SHOTS.mkdir(parents=True, exist_ok=True)
    for scheme in ("light", "dark"):
        page.emulate_media(color_scheme=scheme)
        page.goto(f"{origin}/")
        page.wait_for_function("window.__sources.length >= 1")
        header = page.locator(".app-header")
        assert header.is_visible()
        assert header.locator(".health").count() == 0
        page.evaluate("window.__sources.forEach(s => s.onerror())")
        assert page.get_by_role("alert").count() == 0
        page.evaluate("window.__skew = 6000")
        notice = page.get_by_role("alert").filter(has_text="Connection lost.")
        notice.wait_for()
        assert notice.get_by_text(
            "Connection lost. Your draft and failed messages are saved on this device."
        ).is_visible()
        assert notice.get_by_role("button", name="Retry").is_visible()
        assert notice.get_by_role("button", name="Dismiss").is_visible()
        page.screenshot(
            path=str(SHOTS / f"connection-failure-390-{scheme}.jpg"),
            type="jpeg",
            quality=60,
            clip={"x": 0, "y": 0, "width": 390, "height": 200},
        )
        page.evaluate("window.__sources.forEach(s => s.onopen())")
        notice.wait_for(state="detached")
    page.emulate_media(color_scheme="light")


def test_chat_list_health_indicator_updates_without_a_banner(browser_page):
    page, _, _, origin, _ = browser_page
    page.add_init_script(FAKE_EVENT_SOURCE)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/")
    page.wait_for_function("window.__sources.length >= 1")
    page.evaluate("window.__sources[0].onerror()")
    assert page.get_by_role("alert").count() == 0
    header = page.locator(".app-header")
    assert header.bounding_box()["height"] >= 60
    assert header.locator(".health").count() == 0
    page.evaluate("window.__skew = 6000")
    notice = page.get_by_role("alert").filter(has_text="Connection lost.")
    notice.wait_for()
    assert notice.get_by_text(
        "Your draft and failed messages are saved on this device."
    ).is_visible()
    assert notice.get_by_role("button", name="Retry").is_visible()
    page.evaluate("window.__sources[0].onopen()")
    notice.wait_for(state="detached")
    assert page.locator(".app-header .health").count() == 0


def test_plans_starts_fallback_polling_after_connection_outage(browser_page):
    page, _, _, origin, _ = browser_page
    page.add_init_script(FAKE_EVENT_SOURCE)
    requests = []
    page.on(
        "request",
        lambda request: (
            requests.append(request.url) if "/api/plans" in request.url else None
        ),
    )
    page.goto(f"{origin}/plans")
    page.get_by_role("heading", name="Plans", level=1).wait_for()
    page.wait_for_function("window.__sources.length >= 1")
    page.evaluate("window.__sources[0].onerror()")
    assert page.get_by_role("alert").count() == 0
    page.evaluate("window.__skew = 6000")
    page.get_by_role("alert").filter(has_text="Connection lost.").wait_for()
    initial_count = len(requests)
    page.wait_for_timeout(3500)
    assert len(requests) > initial_count


def test_queue_and_plan_routes_are_served(browser_page):
    page, _, _, origin, _ = browser_page
    page.goto(f"{origin}/queue")
    page.wait_for_url("**/thread/manager")
    assert page.url.endswith("/thread/manager")
    response = page.request.get(f"{origin}/plans/some-plan")
    assert response.ok
    assert "<html" in response.text()


def test_chat_list_shows_running_agent_sessions(browser_page):
    page, _, _, origin, _ = browser_page
    page.route(
        "**/api/home",
        lambda route: route.fulfill(
            json={
                "roles": [
                    {
                        "role": "builder",
                        "agent_id": "builder-1",
                        "state": "running",
                        "queued": 0,
                        "needs_you": 0,
                        "current": None,
                    },
                    {
                        "role": "reviewer",
                        "agent_id": "reviewer-1",
                        "state": "running",
                        "queued": 0,
                        "needs_you": 0,
                        "current": None,
                    },
                ]
            }
        ),
    )
    page.route(
        "**/api/roles",
        lambda route: route.fulfill(
            json={"roles": {"manager-bot": {"enabled": False}}}
        ),
    )
    page.route(
        "**/api/instance-threads**",
        lambda route: route.fulfill(
            json={
                "threads": [
                    {
                        "thread_key": "instance:builder-1",
                        "agent_id": "builder-1",
                        "plan_id": None,
                        "role": "builder",
                        "label": "Builder",
                        "state": "running",
                        "last_activity": "2026-10-27T10:00:00Z",
                    },
                    {
                        "thread_key": "instance:reviewer-1",
                        "agent_id": "reviewer-1",
                        "plan_id": None,
                        "role": "reviewer",
                        "label": "Reviewer",
                        "state": "running",
                        "last_activity": "2026-10-27T09:00:00Z",
                    },
                ]
            }
        ),
    )
    page.route("**/api/agents", lambda route: route.fulfill(json=[]))
    page.route("**/api/pins", lambda route: route.fulfill(json={"pins": []}))
    page.route(
        "**/api/needs-you-count",
        lambda route: route.fulfill(json={"needs_you_count": 0}),
    )
    page.route("**/api/threads", lambda route: route.fulfill(json=[]))
    page.route(
        "**/api/chat?thread=main**",
        lambda route: route.fulfill(json={"messages": [], "latest_seq": 0}),
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.emulate_media(color_scheme="light")
    page.goto(f"{origin}/")
    page.locator(".chat-row").filter(has_text="Builder").wait_for()
    page.locator(".chat-row").filter(has_text="Reviewer").wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
