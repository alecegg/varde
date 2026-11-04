from __future__ import annotations

import copy
import os
import re
import time
from pathlib import Path

import pytest
import test_web_browser

pytestmark = pytest.mark.slow

browser_page = test_web_browser.browser_page

SHOTS = Path(
    "/Users/alec/source/agent-memory/projects/varde-py/working/plans/"
    "2026-10-22-dashboard-followups/notes"
)


def task(task_id, title, status):
    return {"id": task_id, "title": title, "status": status}


ORCHESTRATORS = {
    "plans": [
        {
            "id": "dashboard-ux2",
            "plan_id": "dashboard-ux2",
            "title": "Dashboard UX round 2",
            "status": "running",
            "activity": "running",
            "workers": [
                {"id": "w1", "title": "Reviewer one", "status": "running"},
                {"id": "w2", "title": "Reviewer two", "status": "running"},
            ],
            "open_questions": 0,
            "now": "T2 drafting thread views.",
            "owner": "orchestrator dashboard-ux2",
            "model": "claude-sonnet-5-5",
            "worktree": "worktree/dashboard-ux2",
            "queue": [
                task("T0", "Research note", "done"),
                task("T1", "Navigation", "in_progress"),
                task("T2", "Thread views", "asking"),
                task("T3", "Roles", "todo"),
            ],
        },
        {
            "id": "dashboard-queue",
            "plan_id": "dashboard-queue",
            "title": "Dashboard queue",
            "status": "asking",
            "activity": "waiting",
            "workers": [],
            "open_questions": 1,
            "queue": [task("T0", "Merge", "done")],
        },
        {
            "id": "old-plan",
            "plan_id": "old-plan",
            "title": "Old finished plan",
            "status": "done",
            "activity": "done",
            "queue": [],
        },
    ],
    "infrastructure": [],
    "agents": [],
}
THREADS = [
    {
        "thread_id": "dashboard-ux2",
        "plan_id": "dashboard-ux2",
        "sender": "orchestrator",
        "title": "Which nav option?",
        "open_count": 1,
    },
    {
        "thread_id": "quiet",
        "plan_id": "quiet",
        "sender": "orchestrator",
        "title": "Already answered",
        "open_count": 0,
    },
]


def mock_plans(page, data=ORCHESTRATORS):
    page.route("**/api/orchestrators", lambda r: r.fulfill(json=data))
    page.route("**/api/plans", lambda r: r.fulfill(json=plan_list(data)))
    page.route(
        re.compile(r".*/api/plans/[^/]+/task-queue$"),
        lambda r: r.fulfill(json={"items": [], "role_sessions": []}),
    )
    page.route("**/api/threads", lambda r: r.fulfill(json=THREADS))
    test_web_browser.mock_events(page, data)


def plan_list(data):
    status_map = {
        "running": "in_progress",
        "active": "in_progress",
        "backlog": "queued",
        "asking": "blocked",
        "blocked": "blocked",
        "done": "done",
        "completed": "done",
        "cancelled": "done",
    }
    rows = []
    for plan in data.get("plans", []):
        status = status_map.get(str(plan.get("status", "")).lower(), "needs_review")
        rows.append(
            {
                "id": plan.get("id", plan.get("plan_id", "plan")),
                "title": plan.get("title", "Plan"),
                "label": plan.get("label", plan.get("title", "Plan")),
                "status": status,
                "queue_position": len(rows) + 1 if status == "queued" else None,
                "open_comments": 0,
                "updated": "2026-10-28T00:00:00Z",
            }
        )
    return rows


def test_mailbox_only_snapshot_does_not_reload_plans(browser_page):
    page, _, _, origin, _ = browser_page
    mock_plans(page)
    requests = 0

    def plans(route):
        nonlocal requests
        requests += 1
        route.fulfill(json=plan_list(ORCHESTRATORS))

    page.route("**/api/plans", plans)
    page.route(
        "**/events",
        # Only mailbox snapshots are under test; keep the SSE channel quiet.
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.goto(f"{origin}/plans")
    page.get_by_role("heading", name="Plans", level=1).wait_for()
    page.get_by_role("link", name=re.compile("Dashboard UX round 2")).wait_for()
    page.get_by_text("Dashboard UX round 2", exact=True).wait_for()
    assert requests == 1

    page.evaluate(
        "topics => window.dispatchEvent(new CustomEvent('runner:snapshot', "
        "{detail: {topics}}))",
        ["mailbox"],
    )
    page.wait_for_timeout(100)

    assert requests == 1


def use_short_request_timeout(page, delay_ms=100):
    page.add_init_script(
        f"""(() => {{
          AbortSignal.timeout = () => {{
            const controller = new AbortController();
            setTimeout(() => controller.abort(
              new DOMException('The operation timed out', 'TimeoutError')
            ), {delay_ms});
            return controller.signal;
          }};
        }})();"""
    )


def test_root_loads_chat_list(browser_page):
    page, _, _, origin, _ = browser_page
    page.goto(f"{origin}/")
    page.get_by_role("heading", name="Chats").wait_for()
    page.get_by_text("No conversations yet", exact=True).wait_for()
    page.locator(".pin-section .needs-action").wait_for(state="detached")
    assert page.url == f"{origin}/"


def test_plans_page_sections_and_mobile_fit(browser_page):
    page, _, _, origin, _ = browser_page
    mock_plans(page)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/plans")
    page.get_by_role("heading", name="Plans", level=1).wait_for()
    page.get_by_role("region", name="In progress").wait_for()
    assert page.get_by_role("region", name="Blocked").count() == 1
    assert (
        page.get_by_role("link", name=re.compile("Dashboard UX round 2")).get_attribute(
            "href"
        )
        == "/plans/dashboard-ux2"
    )
    done = page.locator("details.done")
    assert done.get_attribute("open") is None
    done.locator("summary").click()
    assert done.get_by_role("link", name=re.compile("Old finished plan")).is_visible()
    assert page.evaluate("document.documentElement.scrollWidth") <= 390


def test_plans_load_error_can_be_retried(browser_page):
    page, _, _, origin, _ = browser_page
    mock_plans(page)
    page.route(
        "**/events",
        # The API's malformed JSON is the failure under test; keep the unrelated
        # SSE channel quiet to avoid a browser-level connection error.
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    attempts = 0

    def plans(route):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            route.fulfill(content_type="application/json", body="{")
        else:
            route.fulfill(json=plan_list(ORCHESTRATORS))

    page.route("**/api/plans", plans)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/plans")
    error = page.get_by_role("alert")
    error.wait_for()
    assert error.locator("p").inner_text() == (
        "Could not load plans. Check your connection and retry."
    )
    assert error.get_by_role("button", name="Retry").is_visible(), error.inner_text()
    error.get_by_role("button", name="Retry").click()
    page.get_by_text("Dashboard UX round 2", exact=True).wait_for()
    assert attempts >= 2
    assert page.get_by_role("alert").count() == 0
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_stalled_plans_request_eventually_shows_retry(browser_page):
    page, _, _, origin, _ = browser_page
    mock_plans(page)
    use_short_request_timeout(page)
    page.route("**/api/plans", lambda route: None)
    page.route(
        "**/events",
        # Hold a quiet SSE connection while the API request timeout is tested.
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.set_viewport_size({"width": 390, "height": 844})
    with page.expect_request("**/api/plans"):
        page.goto(f"{origin}/plans")

    error = page.get_by_role("alert")
    error.wait_for()
    assert error.locator("p").inner_text() == (
        "Could not load plans. Check your connection and retry."
    )
    assert error.get_by_role("button", name="Retry").is_visible()
    assert page.locator(".summary-skeleton").count() == 0


def test_stale_plans_timeout_cannot_replace_newer_sse_snapshot(browser_page):
    page, _, _, origin, _ = browser_page
    mock_plans(page)
    use_short_request_timeout(page)
    latest = copy.deepcopy(ORCHESTRATORS)
    latest["plans"][0]["title"] = "Fresh SSE plan"
    request_count = 0

    def hold_initial_request(route):
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return
        route.fulfill(json=plan_list(latest))

    page.route("**/api/plans", hold_initial_request)
    page.route(
        "**/events",
        # This test injects the newer snapshot directly; keep network SSE inert.
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.set_viewport_size({"width": 390, "height": 844})
    with page.expect_request("**/api/plans"):
        page.goto(f"{origin}/plans")

    page.evaluate(
        "topics => window.dispatchEvent(new CustomEvent('runner:snapshot', "
        "{detail: {topics}}))",
        ["plans"],
    )
    page.get_by_text("Fresh SSE plan", exact=True).wait_for()
    page.wait_for_timeout(350)

    assert page.get_by_role("alert").count() == 0
    assert page.get_by_text("Fresh SSE plan", exact=True).is_visible()
    assert page.locator(".summary-skeleton").count() == 0


def test_stale_plans_response_cannot_replace_newer_sse_snapshot(browser_page):
    page, _, _, origin, _ = browser_page
    mock_plans(page)
    use_short_request_timeout(page, delay_ms=1_000)
    pending = []
    latest = copy.deepcopy(ORCHESTRATORS)
    latest["plans"][0]["title"] = "Fresh SSE plan"
    request_count = 0

    def hold_request(route):
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            pending.append(route)
        else:
            route.fulfill(json=plan_list(latest))

    page.route("**/api/plans", hold_request)
    page.route(
        "**/events",
        # This test injects the newer snapshot directly; network SSE stays inert.
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.set_viewport_size({"width": 390, "height": 844})
    with page.expect_request("**/api/plans"):
        page.goto(f"{origin}/plans")
    deadline = time.monotonic() + 10
    while not pending and time.monotonic() < deadline:
        page.wait_for_timeout(25)
    assert pending

    page.evaluate(
        "topics => window.dispatchEvent(new CustomEvent('runner:snapshot', "
        "{detail: {topics}}))",
        ["plans"],
    )
    page.get_by_text("Fresh SSE plan", exact=True).wait_for()
    stale = copy.deepcopy(ORCHESTRATORS)
    stale["plans"][0]["title"] = "Stale API plan"
    for route in pending:
        route.fulfill(json=plan_list(stale))
    page.wait_for_timeout(100)

    assert page.get_by_text("Fresh SSE plan", exact=True).is_visible()
    assert page.get_by_text("Stale API plan", exact=True).count() == 0
    assert page.get_by_role("alert").count() == 0


def test_blocked_and_needs_review_are_separate_groups(browser_page):
    page, _, _, origin, _ = browser_page
    rows = [
        {
            "id": "blocked-plan",
            "title": "Blocked plan",
            "label": "Blocked plan",
            "status": "blocked",
            "queue_position": None,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        },
        {
            "id": "review-plan",
            "title": "Needs review plan",
            "label": "Needs review plan",
            "status": "needs_review",
            "queue_position": None,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        },
        {
            "id": "queued-late",
            "title": "Queued later",
            "label": "Queued later",
            "status": "queued",
            "queue_position": 2,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        },
        {
            "id": "queued-first",
            "title": "Queued first",
            "label": "Queued first",
            "status": "queued",
            "queue_position": 1,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        },
    ]
    page.route("**/api/plans", lambda route: route.fulfill(json=rows))
    page.goto(f"{origin}/plans")
    page.get_by_role("heading", name="Blocked", exact=True).wait_for()
    assert page.get_by_role("region", name="Needs review").is_visible()
    queue = page.get_by_role("region", name="Queue")
    assert queue.get_by_role("link", name="Queued first").is_visible()
    assert queue.get_by_role("link", name="Queued later").is_visible()


def test_done_disclosure_stays_open_when_plan_list_refreshes(browser_page):
    page, _, _, origin, _ = browser_page
    current = plan_list(ORCHESTRATORS)
    page.route("**/api/plans", lambda r: r.fulfill(json=current))
    page.goto(f"{origin}/plans")
    done = page.locator("details.done")
    done.wait_for()
    done.locator("summary").click()
    assert done.get_attribute("open") is not None
    current[2]["label"] = "Updated after refresh"
    page.route("**/api/plans", lambda route: route.fulfill(json=current))
    with page.expect_response(lambda response: response.url.endswith("/api/plans")):
        page.evaluate(
            "topics => window.dispatchEvent(new CustomEvent('runner:snapshot', "
            "{detail: {topics}}))",
            ["plans"],
        )
    done.get_by_text("Updated after refresh").wait_for()
    assert done.get_attribute("open") is not None


def test_done_disclosure_can_be_opened_after_reload(browser_page):
    page, _, _, origin, _ = browser_page
    mock_plans(page)
    page.goto(f"{origin}/plans")
    done = page.locator("details.done")
    done.locator("summary").click()
    assert done.get_attribute("open") is not None
    page.reload()
    done = page.locator("details.done")
    done.wait_for()
    assert done.get_attribute("open") is None
    done.locator("summary").click()
    assert done.get_by_role("link", name=re.compile("Old finished plan")).is_visible()


def test_plans_page_screenshots(browser_page):
    page, _, _, origin, _ = browser_page
    mock_plans(page)
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": 390, "height": 1500})
    for scheme in ("light", "dark"):
        page.emulate_media(color_scheme=scheme)
        page.goto(f"{origin}/plans")
        page.get_by_role("heading", name="Plans", level=1).wait_for()
        page.screenshot(
            path=str(SHOTS / f"plans-{scheme}.jpg"),
            type="jpeg",
            quality=65,
            full_page=True,
        )
    page.emulate_media(color_scheme="light")


@pytest.mark.parametrize("theme", ("light", "dark"))
def test_plan_status_badges_have_distinct_labels(browser_page, theme):
    page, _, _, origin, _ = browser_page
    rows = [
        {
            "id": "active",
            "title": "Active plan",
            "label": "Active plan",
            "status": "in_progress",
            "updated": "2026-10-28T00:00:00Z",
            "open_comments": 0,
            "queue_position": None,
        },
        {
            "id": "blocked",
            "title": "Blocked plan",
            "label": "Blocked plan",
            "status": "blocked",
            "updated": "2026-10-28T00:00:00Z",
            "open_comments": 0,
            "queue_position": None,
        },
        {
            "id": "review",
            "title": "Review plan",
            "label": "Review plan",
            "status": "needs_review",
            "updated": "2026-10-28T00:00:00Z",
            "open_comments": 0,
            "queue_position": None,
        },
        {
            "id": "queued",
            "title": "Queued plan",
            "label": "Queued plan",
            "status": "queued",
            "updated": "2026-10-28T00:00:00Z",
            "open_comments": 0,
            "queue_position": 1,
        },
    ]
    page.route("**/api/plans", lambda r: r.fulfill(json=rows))
    page.emulate_media(color_scheme=theme)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/plans")
    page.get_by_role("heading", name="Plans", level=1).wait_for()
    page.get_by_role("link", name="Active plan").wait_for()
    for label in ("In progress", "Blocked", "Needs review"):
        assert page.get_by_text(label, exact=True).first.is_visible()
    queue = page.get_by_role("region", name="Queue")
    assert queue.get_by_role("link", name="Queued plan").is_visible()


LABEL_SHOTS = Path(
    "/Users/alec/source/agent-memory/projects/varde-py/working/plans/"
    "2026-10-22-plan-labels-groups/notes"
)


def labelled_data():
    data = copy.deepcopy(ORCHESTRATORS)
    plans = data["plans"]
    plans[0] |= {
        "label": "Thread views",
        "purpose": "Keep plan work easy to follow.",
        "group_name": "Dashboard",
    }
    plans[1] |= {"label": "Queue cleanup", "group_name": "Agent management"}
    plans[2] |= {"label": "Old plan", "group_name": "Dashboard"}
    plans.append(
        {
            "id": "qs-build",
            "plan_id": "qs-build",
            "title": "Quality score build with a very long over-specific title",
            "label": "Score build",
            "group_name": "Quality score",
            "status": "running",
            "activity": "running",
            "workers": [],
            "open_questions": 0,
            "queue": [task("T0", "Spike", "done"), task("T1", "Build", "todo")],
        }
    )
    data["past"] = [
        {
            "id": "gone",
            "plan_id": "gone",
            "address": "gone-orch",
            "title": "Gone plan full title",
            "label": "Gone plan",
            "group_name": "Quality score",
            "status": "completed",
            "activity": "done",
            "queue": [],
        }
    ]
    return data


def mock_labelled(page):
    data = labelled_data()
    page.route("**/api/orchestrators", lambda r: r.fulfill(json=data))
    page.route("**/api/plans", lambda r: r.fulfill(json=plan_list(data)))
    page.route("**/api/threads", lambda r: r.fulfill(json=THREADS))
    test_web_browser.mock_events(page, data)


def test_plan_list_uses_label_as_row_title(browser_page):
    page, _, _, origin, _ = browser_page
    mock_labelled(page)
    page.goto(f"{origin}/plans")
    row = page.get_by_role("link", name=re.compile("Thread views"))
    row.wait_for()
    assert row.is_visible()
    assert row.get_attribute("href") == "/plans/dashboard-ux2"
    assert (
        page.get_by_role("link", name=re.compile("Dashboard UX round 2")).count() == 0
    )


def test_plan_page_shows_group_chip_and_full_title_with_blank_label(browser_page):
    page, _, _, origin, _ = browser_page
    base = {
        "status": "backlog",
        "plan_text": "body",
        "tasks": [],
        "notes_status": "present",
        "review_status": "none",
        "comments": [],
    }
    labelled = base | {
        "id": "with-chip",
        "title": "Full plan title",
        "label": "Short",
        "group_name": "Dashboard",
    }
    blank = base | {
        "id": "no-chip",
        "title": "Untagged title",
        "label": "",
        "group_name": "",
    }
    page.route("**/api/plans/with-chip", lambda r: r.fulfill(json=labelled))
    page.route("**/api/plans/no-chip", lambda r: r.fulfill(json=blank))
    page.route(
        re.compile(r".*/api/plans/[^/]+/task-queue$"),
        lambda r: r.fulfill(json={"items": [], "role_sessions": []}),
    )
    page.goto(f"{origin}/plans/with-chip")
    page.get_by_role("heading", name="Full plan title", level=1).wait_for()
    assert page.locator(".group-chip").inner_text() == "Dashboard"
    page.goto(f"{origin}/plans/no-chip")
    page.get_by_role("heading", name="Untagged title", level=1).wait_for()
    assert page.locator(".group-chip").count() == 0


def test_label_chip_screenshots(browser_page):
    page, _, _, origin, _ = browser_page
    mock_labelled(page)
    LABEL_SHOTS.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": 390, "height": 1500})
    page.goto(f"{origin}/plans")
    page.get_by_role("link", name=re.compile("Thread views")).wait_for()
    page.screenshot(path=str(LABEL_SHOTS / "t4-cards-chips-narrow.png"), full_page=True)
    assert page.locator(".group-chip").count() == 0
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.set_viewport_size({"width": 1100, "height": 1100})
    page.screenshot(path=str(LABEL_SHOTS / "t4-cards-chips-wide.png"), full_page=True)


def test_plans_page_has_no_group_filter_or_sideways_scrolling_rows(browser_page):
    page, _, _, origin, _ = browser_page
    mock_labelled(page)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/plans")
    page.get_by_role("link", name=re.compile("Thread views")).wait_for()
    assert page.locator(".group-filter").count() == 0
    scrolling = page.evaluate(
        "() => [...document.querySelectorAll('.app-content *')].filter(el => {"
        " const s = getComputedStyle(el);"
        " return ['auto', 'scroll'].includes(s.overflowX)"
        " && el.scrollWidth > el.clientWidth; }).length"
    )
    assert scrolling == 0
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.get_by_role("link", name=re.compile("Score build")).is_visible()
    shot = os.environ.get("PLANS_390_SHOT")
    if shot:
        page.screenshot(path=shot)


def test_blocked_plans_show_in_blocked_section(browser_page):
    page, _, _, origin, _ = browser_page
    rows = plan_list(ORCHESTRATORS)
    rows[0]["status"] = "blocked"
    rows[0]["title"] = "Paseo disk writes"
    rows[0]["label"] = "Paseo disk writes"
    page.route("**/api/plans", lambda route: route.fulfill(json=rows))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/plans")
    page.get_by_role("heading", name="Plans", level=1).wait_for()
    blocked = page.get_by_role("region", name="Blocked")
    blocked.get_by_role("link", name=re.compile("Paseo disk writes")).wait_for()
    assert blocked.get_by_role(
        "link", name=re.compile("Paseo disk writes")
    ).is_visible()
    assert blocked.get_by_role("heading", name="Blocked").is_visible()
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    shot = os.environ.get("PLANS_390_SHOT")
    if shot:
        page.screenshot(path=shot, full_page=True)
