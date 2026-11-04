from contextlib import suppress
from typing import cast

from starlette.applications import Starlette
from test_web import app_request
from varde_runner.cache import SingleFlightCache
from varde_runner.open_decisions import open_decision_items
from varde_runner.threads import (
    group_threads,
    is_user_facing_message,
    open_needs_you_count,
)
from varde_runner.web.app import (
    DashboardData,
    _bound_addresses_for_closed_plans,
    _closed_plan_ids,
)
from varde_runner.web.threads_route import _plan_titles, create_threads_routes


def test_user_facing_thread_message_filter_keeps_requests_and_user_responses():
    assert is_user_facing_message({"kind": "permission"})
    assert is_user_facing_message({"kind": "needs-decision"})
    assert is_user_facing_message({"kind": "info", "to": "user"})
    assert is_user_facing_message({"kind": "info", "from": "user"})
    assert is_user_facing_message({"kind": "info", "reply": "User replied"})
    assert not is_user_facing_message({"kind": "info", "to": "main"})
    assert not is_user_facing_message({"kind": "info", "to": "reviewer"})
    assert not is_user_facing_message({"kind": "info-failure", "to": "relay"})


def test_open_needs_you_count_matches_open_items_and_ignores_stale_threads():
    assert (
        open_needs_you_count(
            [
                {"open_count": 2},
                {"open_count": 0, "stale_count": 1},
                {"open_count": 0, "stale_count": 0},
            ]
        )
        == 2
    )


def test_needs_you_derivation_excludes_closed_and_answered_and_keeps_count_in_sync():
    items = [
        {
            "msg_id": "merged-ready",
            "sender": "merged-agent",
            "kind": "merge-ready",
            "state": "pending",
            "ts": "2026-10-28T10:00:00Z",
        },
        {
            "msg_id": "answered-request",
            "sender": "active-agent",
            "kind": "needs-user",
            "state": "pending",
            "ts": "2026-10-28T10:00:00Z",
        },
        {
            "msg_id": "concluded-request",
            "sender": "concluded-agent",
            "kind": "needs-user",
            "state": "pending",
            "ts": "2026-10-28T10:00:00Z",
        },
        {
            "msg_id": "open-request",
            "sender": "open-agent",
            "kind": "needs-user",
            "state": "pending",
            "ts": "2026-10-28T10:00:00Z",
        },
    ]
    plans = [
        {"id": "merged-plan", "merge_state": "merged"},
        {"id": "concluded-plan", "status": "concluded"},
    ]
    bindings = [
        {"address": "merged-agent", "plan_id": "merged-plan"},
        {"address": "active-agent", "plan_id": "active-plan"},
        {"address": "concluded-agent", "plan_id": "concluded-plan"},
        {"address": "open-agent", "plan_id": "open-plan"},
    ]
    closed_addresses = _closed_plan_ids(plans) | _bound_addresses_for_closed_plans(
        plans, bindings
    )
    opened = open_decision_items(
        items,
        [
            {
                "from": "main",
                "to": "active-agent",
                "ts": "2026-10-28T11:00:00Z",
            }
        ],
        set(),
        {binding["address"] for binding in bindings},
        closed_addresses,
    )
    open_ids = {item["msg_id"] for item in opened}
    threads = group_threads(items, open_ids)

    assert open_ids == {"open-request"}
    assert open_needs_you_count(threads) == len(opened) == 1


def test_group_threads_by_plan_or_sender_and_order_by_latest_timestamp():
    rows = [
        {
            "msg_id": "old",
            "plan_id": "plan-a",
            "sender": "agent-a",
            "state": "pending",
            "ts": "2026-10-20T10:00:00Z",
            "body": "Earlier answer",
        },
        {
            "msg_id": "new",
            "plan_id": "plan-a",
            "sender": "agent-a",
            "state": "answered",
            "ts": "2026-10-21T10:00:00Z",
            "body": "Question two",
        },
        {
            "msg_id": "sender-thread",
            "sender": "agent-b",
            "state": "pending",
            "ts": "2026-10-21T09:00:00Z",
            "body": "Other body",
        },
    ]

    assert group_threads(rows, {"old", "sender-thread"}) == [
        {
            "thread_id": "plan:plan-a",
            "plan_id": "plan-a",
            "sender": "agent-a",
            "title": "",
            "open_count": 1,
            "stale_count": 0,
            "last_open_ts": "2026-10-20T10:00:00Z",
            "last_ts": "2026-10-21T10:00:00Z",
            "last_preview": "Question two",
            "user_message": False,
            "decision_ids": ["old", "new"],
        },
        {
            "thread_id": "sender:agent-b",
            "plan_id": None,
            "sender": "agent-b",
            "title": "",
            "open_count": 1,
            "stale_count": 0,
            "last_open_ts": "2026-10-21T09:00:00Z",
            "last_ts": "2026-10-21T09:00:00Z",
            "last_preview": "Other body",
            "user_message": False,
            "decision_ids": ["sender-thread"],
        },
    ]


def test_group_threads_separates_plan_sender_and_unattributed_items():
    rows = [
        {"msg_id": "plan", "plan_id": "same", "sender": "other", "ts": "3"},
        {"msg_id": "sender", "sender": "same", "ts": "2"},
        {"msg_id": "none-a", "ts": "1"},
        {"msg_id": "none-b", "ts": "0"},
    ]

    assert {thread["thread_id"] for thread in group_threads(rows)} == {
        "plan:same",
        "sender:same",
        "message:none-a",
        "message:none-b",
    }


def test_real_shaped_mailbox_groups_plans_and_counts_only_open_ids():
    rows = [
        {
            "msg_id": f"m-{index:08x}",
            "sender": "varde-watch" if index % 2 == 0 else f"agent-{index}",
            "source_agent": "varde-watch" if index % 2 == 0 else f"agent-{index}",
            "plan_id": None,
            "kind": "needs-user",
            "state": "pending",
            "ts": f"2026-10-14T{index % 24:02}:00:00Z",
            "body": f"needs-user plan-{(index // 2) % 4} please review",
        }
        for index in range(106)
    ]
    rows.append(
        {
            "msg_id": "m-open0001",
            "sender": "reviewer",
            "plan_id": "plan-open",
            "state": "pending",
            "ts": "2026-10-21T10:00:00Z",
            "body": "Open",
        }
    )

    threads = group_threads(rows, {"m-open0001"})
    by_id = {thread["thread_id"]: thread for thread in threads}

    assert {key for key in by_id if key.startswith("plan:")} == {
        "plan:plan-0",
        "plan:plan-1",
        "plan:plan-2",
        "plan:plan-3",
        "plan:plan-open",
    }
    assert by_id["plan:plan-open"]["open_count"] == 1
    assert by_id["plan:plan-open"]["last_open_ts"] == "2026-10-21T10:00:00Z"
    assert sum(thread["open_count"] for thread in threads) == 1
    assert sum(thread["stale_count"] for thread in threads) == 106


def test_threads_route_returns_grouped_mailbox_items(tmp_path):
    folder = tmp_path / "plans" / "lexical-rank"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text("---\ntitle: Lexical ranking\nstatus: done\n---\n")

    class Dashboard:
        async def mailbox_items(self):
            return [
                {
                    "msg_id": "question-1",
                    "source_agent": "agent-a",
                    "plan_id": "lexical-rank",
                    "title": "Question",
                    "state": "pending",
                    "ts": "2026-10-21T10:00:00Z",
                    "body": "Question body",
                }
            ]

        async def open_mailbox_items(self, items):
            return [item for item in items if item["msg_id"] == "question-1"]

        async def mailbox_threads(self):
            threads = group_threads(await self.mailbox_items(), {"question-1"})
            return [thread | {"plan_title": "Lexical ranking"} for thread in threads]

    app = Starlette(routes=create_threads_routes(tmp_path))
    app.state.dashboard = Dashboard()

    response = app_request(app, "GET", "/api/threads")

    assert response.status_code == 200
    assert response.json()[0]["decision_ids"] == ["question-1"]
    assert response.json()[0]["plan_title"] == "Lexical ranking"


def test_degraded_route_reports_failed_dashboard_loader(tmp_path):
    dashboard = cast("DashboardData", object.__new__(DashboardData))
    dashboard.read_cache = SingleFlightCache()

    def fail_plan_status():
        raise RuntimeError("plan read failed")

    with suppress(RuntimeError):
        dashboard.read_cache.get("plan_status", 0, fail_plan_status)
    app = Starlette(routes=create_threads_routes(tmp_path))
    app.state.dashboard = dashboard

    response = app_request(app, "GET", "/api/degraded")

    assert response.status_code == 200
    assert response.json() == {"sources": ["plan_status"]}


def test_plan_names_use_label_and_fall_back_to_title(tmp_path):
    labelled = tmp_path / "plans" / "labelled"
    fallback = tmp_path / "plans" / "fallback"
    labelled.mkdir(parents=True)
    fallback.mkdir(parents=True)
    (labelled / "plan.md").write_text(
        "---\ntitle: Long project title\nlabel: Short name\n---\n"
    )
    (fallback / "plan.md").write_text("---\ntitle: Fallback title\n---\n")

    assert _plan_titles(tmp_path) == {
        "labelled": "Short name",
        "fallback": "Fallback title",
    }
