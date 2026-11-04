from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import threading
import time
import urllib.request
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn
from stop_server import stop_server
from varde_data.config import DataConfig
from varde_data.open import open_data
from varde_data.records.addresses import ReaderContext
from varde_runner import GRACEFUL_SHUTDOWN_TIMEOUT
from varde_runner.config import default_toml
from varde_runner.intake import InboxProjector
from varde_runner.plugins import RunnerCapabilities
from varde_runner.plugins.paseo import PaseoPlugin
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.varde_cli import VardeCLI
from varde_runner.web import create_app
from varde_runner.web.app import _open_question_count, _plan_activity, _plan_rows

# A hang guard for the local test server, not a speed assertion: baseline load
# can stall a response for more than 5 s.
HTTP_TIMEOUT_SECONDS = 30


def test_plan_activity_uses_worker_in_plan_task_worktree(tmp_path):
    root = tmp_path / "dashboard-ux"
    plan = {"id": "dashboard-ux", "worktree": str(root), "status": "backlog"}
    agents = [
        {"agent": {"id": "orch", "status": "idle"}},
        {
            "agent": {
                "id": "worker",
                "status": "running",
                "cwd": str(tmp_path / "dashboard-ux-T6"),
            }
        },
    ]

    activity = _plan_activity(plan, agents, agents[0]["agent"])
    assert activity["activity"] == "running" and len(activity["workers"]) == 1


def test_plan_activity_uses_parent_chain_and_maps_finished_tasks():
    plan = {
        "id": "alpha",
        "status": "active",
        "tasks": [{"id": "T1", "status": "completed"}],
    }
    agents = [
        {"agent": {"id": "orch", "status": "idle"}},
        {
            "agent": {
                "id": "builder",
                "status": "running",
                "labels": {"paseo.parent-agent-id": "orch"},
            }
        },
    ]
    activity = _plan_activity(plan, agents, agents[0]["agent"])
    assert activity["activity"] == "running"
    assert [worker["id"] for worker in activity["workers"]] == ["builder"]
    assert (
        _plan_activity({**plan, "status": "finished"}, [], agents[0]["agent"])[
            "activity"
        ]
        == "done"
    )


def test_plan_activity_without_workers_uses_task_progress():
    plan = {
        "id": "alpha",
        "status": "active",
        "tasks": [
            {"id": "T1", "status": "done"},
            {"id": "T2", "status": "todo"},
        ],
    }
    assert (
        _plan_activity(plan, [], {"id": "orch", "status": "idle"})["activity"] == "idle"
    )
    assert (
        _plan_activity(
            {"id": "alpha", "status": "backlog", "tasks": []},
            [],
            {"id": "orch", "status": "idle"},
        )["activity"]
        == "idle"
    )


def test_orchestrator_json_includes_plan_queue_owner_now_and_message_age(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "empty-config"
    config_dir.mkdir()
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(config_dir))
    cli = VardeCLI(
        cwd=tmp_path,
        env={
            "VARDE_WORKING_DIR": str(tmp_path),
            "VARDE_CONFIG_DIR": str(tmp_path / "config"),
            "HOME": str(tmp_path / "home"),
        },
    )
    cli.read_plan_status = lambda: {
        "plans": [
            {
                "id": "plan-alpha",
                "title": "Alpha",
                "status": "active",
                "now": "Build the dashboard",
                "owner": "orchestrator",
                "tasks": [{"id": "B1", "status": "in_progress", "owner": "builder"}],
            }
        ]
    }
    monkeypatch.setattr(
        cli,
        "read_plan_watch",
        lambda: {"events": [{"plan": "plan-alpha", "kind": "active"}]},
    )
    cli.read_address_bindings = lambda: [
        {"address": "plan-alpha", "wake_context": {"paseo_id": "paseo-alpha"}}
    ]
    cli.read_messages = lambda: [
        {
            "id": "recent",
            "from": "builder",
            "to": "orchestrator",
            "ts": "2026-10-19T10:00:00+00:00",
        }
    ]
    app = create_app(
        data_dir=tmp_path / "dashboard", cli=cli, agents=_paseo_alpha_agents
    )

    response = _http_get(app, "/api/orchestrators")

    assert response[0] == 200
    plan = response[1]["plans"][0]
    assert plan["id"] == "plan-alpha"
    assert plan["owner"] == "orchestrator"
    assert plan["now"] == "Build the dashboard"
    assert plan["queue"] == [
        {
            "id": "B1",
            "title": "B1",
            "status": "in_progress",
            "status_at": None,
            "owner": "builder",
            "owner_inherited": False,
        }
    ]
    assert plan["last_message_age"] != "unknown"
    assert plan["agent_id"] == "paseo-alpha"
    assert plan["agent_status"] == "running"
    assert plan["last_activity"] == "2026-10-19T10:04:00Z"
    assert [
        (row["address"], row["status"]) for row in response[1]["infrastructure"]
    ] == [
        ("main", "missing"),
        ("mailman", "missing"),
        ("planner", "invalid"),
    ]
    assert response[1]["agents"] == []


@pytest.mark.parametrize("invalid_harness", [False, True])
def test_unavailable_planner_role_is_logged_and_exposed_in_infrastructure(
    tmp_path, monkeypatch, caplog, invalid_harness
):
    config_text = default_toml()
    if invalid_harness:
        config_text = config_text.replace(
            '[roles.planner]\ntype = "standard"',
            '[roles.planner]\ntype = "invalid-type"',
        )
        expected_status = "invalid"
    else:
        planner_start = config_text.index("[roles.planner]")
        next_section = config_text.find("\n[", planner_start + 1)
        if next_section == -1:
            config_text = config_text[:planner_start]
        else:
            config_text = config_text[:planner_start] + config_text[next_section + 1 :]
        expected_status = "missing"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "runner.toml"
    config_path.write_text(config_text, encoding="utf-8")
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(config_dir))

    class CLI:
        def read_plan(self):
            return {"plans": [], "events": []}

        def read_plan_status(self):
            return {"plans": []}

        def read_plan_watch(self):
            return {"events": []}

        def read_assigned_plans(self):
            return []

        def read_address_bindings(self):
            return []

        def read_messages(self):
            return []

        def send(self, **kwargs):
            return {"id": "sent"}

    app = create_app(data_dir=tmp_path / "dashboard", cli=CLI(), agents=list)

    class Supervisor:
        def approval_waits_for_mailbox(self):
            return []

    async def get_supervisor():
        return Supervisor()

    app.state.dashboard.supervisor_getter = get_supervisor
    response = _http_get(app, "/api/orchestrators")

    assert response[0] == 200
    if expected_status == "missing":
        # RoleConfig.resolve intentionally supplies the default planner role
        # when configuration omits it.
        assert not any(
            row["address"] == "planner" for row in response[1]["infrastructure"]
        )
        assert "Planner role is unavailable" not in caplog.text
        return
    planner = next(
        row for row in response[1]["infrastructure"] if row["address"] == "planner"
    )
    assert planner["status"] == expected_status
    assert "planner" in planner["reason"]
    assert str(config_path) in caplog.text
    assert "Planner role" in caplog.text


def test_valid_planner_role_does_not_add_infrastructure_row(tmp_path, monkeypatch):
    config_dir = tmp_path / "valid-config"
    config_dir.mkdir()
    (config_dir / "runner.toml").write_text(default_toml(), encoding="utf-8")
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(config_dir))

    class CLI:
        def read_plan(self):
            return {"plans": [], "events": []}

        def read_plan_status(self):
            return {"plans": []}

        def read_plan_watch(self):
            return {"events": []}

        def read_assigned_plans(self):
            return []

        def read_address_bindings(self):
            return []

        def read_messages(self):
            return []

        def send(self, **kwargs):
            return {"id": "sent"}

    app = create_app(data_dir=tmp_path / "dashboard", cli=CLI(), agents=list)

    class Supervisor:
        def approval_waits_for_mailbox(self):
            return []

    async def get_supervisor():
        return Supervisor()

    app.state.dashboard.supervisor_getter = get_supervisor
    response = _http_get(app, "/api/orchestrators")

    assert response[0] == 200
    assert [row["address"] for row in response[1]["infrastructure"]] == [
        "main",
        "mailman",
    ]


def _paseo_alpha_agents():
    return [
        {
            "agent": {
                "id": "paseo-alpha",
                "status": "running",
                "lastActivity": "2026-10-19T10:04:00Z",
            }
        }
    ]


def test_paseo_directory_reader_uses_the_existing_adapter():
    async def exercise():
        plugin = PaseoPlugin(Path("unused.sock"), "ws://unused")

        async def request(operation, **payload):
            assert operation == "list_agents"
            return {"agents": [{"agent": {"id": "paseo-agent", "status": "idle"}}]}

        plugin._request = request
        return await plugin.list_agents()

    import asyncio

    assert asyncio.run(exercise()) == [
        {"agent": {"id": "paseo-agent", "status": "idle"}}
    ]


def test_cli_reads_address_binding_json_shape(tmp_path):
    working = tmp_path / "working"
    addresses = open_data(working, DataConfig()).addresses
    marker = addresses.issue("main", supersede=True, now=datetime.now(UTC))
    assert addresses.redeem(
        marker,
        "session-1",
        "codex",
        ReaderContext(paseo_id="p1"),
        now=datetime.now(UTC),
    )
    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": str(working)})
    assert cli.read_address_bindings() == [
        {
            "address": "main",
            "session_id": "session-1",
            "harness": "codex",
            "bound_at": addresses.list_bindings()[0].bound_at.isoformat(),
            "last_seen": addresses.list_bindings()[0].last_seen.isoformat(),
            "token_id": addresses.list_bindings()[0].token_id,
            "cwd": ".",
            "wake_context": {
                "harness": "codex",
                "paseo_id": "p1",
                "session_id": "session-1",
                "cwd": ".",
            },
        }
    ]


def test_cli_reads_all_assigned_plans_from_working_store(tmp_path):
    plans_dir = tmp_path / "plans"
    assigned = plans_dir / "group" / "assigned-plan" / "plan.md"
    assigned.parent.mkdir(parents=True)
    assigned.write_text(
        "---\ntitle: Assigned\nlabel: Assigned label\nstatus: backlog\n"
        "assigned_to: orchestrator-2\n---\n",
        encoding="utf-8",
    )
    unassigned = plans_dir / "unassigned" / "plan.md"
    unassigned.parent.mkdir()
    unassigned.write_text("---\nstatus: backlog\n---\n", encoding="utf-8")
    cli = VardeCLI(cwd=tmp_path)
    cli._working_path = tmp_path

    assert cli.read_assigned_plans() == [
        {
            "id": "assigned-plan",
            "title": "Assigned",
            "label": "Assigned label",
            "status": "backlog",
            "assigned_to": "orchestrator-2",
        }
    ]


def test_cli_missing_working_directory_logs_assigned_plan_read(caplog, tmp_path):
    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": ""})
    cli._json = lambda *_args, timeout=30: {}

    assert cli.read_assigned_plans() == []
    assert "assigned plans" in caplog.text
    assert "working directory" in caplog.text


def test_orchestrator_row_joins_plan_by_assigned_to_slot():
    plans, _, _ = _plan_rows(
        {
            "plans": [
                {
                    "id": "2026-10-20-semble-compare",
                    "status": "active",
                    "title": "Semble comparison",
                    "assigned_to": "orchestrator-2",
                    "tasks": [
                        {"id": "compare", "title": "Compare APIs", "status": "todo"}
                    ],
                }
            ]
        },
        {"events": []},
        [],
        object(),
        [{"address": "orchestrator-2"}],
        [],
    )

    assert len(plans) == 1
    assert plans[0]["id"] == "2026-10-20-semble-compare"
    assert plans[0]["plan_id"] == "2026-10-20-semble-compare"
    assert plans[0]["address"] == "orchestrator-2"
    assert plans[0]["assigned_to"] == "orchestrator-2"
    assert plans[0]["plan_joined"] is True
    assert plans[0]["activity"] != "unknown"
    assert plans[0]["activity"] == "stalled"
    assert plans[0]["title"] == "Semble comparison"
    assert plans[0]["now"] == "unknown"
    assert plans[0]["queue"][0]["id"] == "compare"


def test_orchestrator_row_joins_backlog_plan_by_assigned_to_slot():
    plans, _, _ = _plan_rows(
        {"plans": []},
        {"events": []},
        [],
        object(),
        [
            {
                "address": "orchestrator-2",
                "wake_context": {"paseo_id": "orch-2"},
            }
        ],
        [{"id": "orch-2", "status": "idle"}],
        assigned_plans=[
            {
                "id": "2026-10-22-dashboard-assigned-plan-join",
                "status": "backlog",
                "title": "Dashboard assigned plan join",
                "label": "Assigned plan join",
                "assigned_to": "orchestrator-2",
                "tasks": [
                    {"id": "join", "title": "Join assigned plans", "status": "todo"}
                ],
            }
        ],
    )

    assert len(plans) == 1
    assert plans[0]["plan_joined"] is True
    assert plans[0]["label"] == "Assigned plan join"
    assert plans[0]["title"] == "Dashboard assigned plan join"
    assert plans[0]["activity"] == "running"
    assert plans[0]["queue"][0]["title"] == "Join assigned plans"


def test_orchestrator_slot_prefers_nonterminal_plan_over_stale_assignment():
    plans, _, _ = _plan_rows(
        {
            "plans": [
                {
                    "id": "current-plan",
                    "status": "active",
                    "title": "Current plan",
                    "assigned_to": "orchestrator-2",
                },
                {
                    "id": "old-plan",
                    "status": "concluded",
                    "title": "Old plan",
                    "assigned_to": "orchestrator-2",
                },
            ]
        },
        {"events": []},
        [],
        object(),
        [{"address": "orchestrator-2", "wake_context": {"paseo_id": "orch-2"}}],
        [{"id": "orch-2", "status": "idle"}],
    )

    assert len(plans) == 1
    assert plans[0]["id"] == "current-plan"


def test_orchestrator_slot_prefers_watch_plan_over_store_only_plan():
    plans, _, _ = _plan_rows(
        {"plans": []},
        {
            "events": [],
            "plans": [
                {
                    "id": "watch-plan",
                    "status": "active",
                    "title": "Watch plan",
                    "assigned_to": "orchestrator-2",
                }
            ],
        },
        [],
        object(),
        [{"address": "orchestrator-2", "wake_context": {"paseo_id": "orch-2"}}],
        [{"id": "orch-2", "status": "idle"}],
        assigned_plans=[
            {
                "id": "store-plan",
                "status": "active",
                "title": "Store plan",
                "assigned_to": "orchestrator-2",
            }
        ],
    )

    assert len(plans) == 1
    assert plans[0]["id"] == "watch-plan"


def test_orchestrator_rows_join_bindings_and_separate_agents(tmp_path, monkeypatch):
    config_dir = tmp_path / "empty-config"
    config_dir.mkdir()
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(config_dir))

    class CLI:
        def read_plan_status(self):
            return {"plans": [{"id": "p1", "status": "active"}]}

        def read_plan_watch(self):
            return {"events": [{"plan": "p1", "kind": "unmapped"}]}

        def read_plan(self):
            return {"events": []}

        def read_address_bindings(self):
            return [
                {"address": "p1", "wake_context": {"paseo_id": "orch"}},
                {"address": "main", "wake_context": {"paseo_id": "main-agent"}},
                {"address": "mailman", "wake_context": {"paseo_id": "mail-agent"}},
                {"address": "extra-bound", "wake_context": {"paseo_id": "extra"}},
            ]

        def read_messages(self):
            return []

        def read_plan_tasks(self, plan_id):
            return []

        def read_plan_summary(self, plan_id):
            return {"owner": "plan-owner"}

        def send(self, **kwargs):
            return {"id": "sent"}

    agents = [
        {
            "agent": {
                "id": "orch",
                "status": "running",
                "title": "Plan orchestrator",
                "model": "gpt-6-luna",
                "lastActivity": "now",
            }
        },
        {
            "agent": {
                "id": "builder",
                "status": "running",
                "lastActivity": "later",
            }
        },
        {"agent": {"id": "unlabeled", "status": "idle"}},
        {"agent": {"id": "main-agent", "status": "idle", "title": "Main"}},
        {"agent": {"id": "mail-agent", "status": "running", "title": "Mailman"}},
        {"agent": {"id": "extra", "status": "idle", "title": "Extra binding"}},
    ]
    app = create_app(data_dir=tmp_path / "dash", cli=CLI(), agents=lambda: agents)
    result = _http_get(app, "/api/orchestrators")[1]
    assert {plan["id"] for plan in result["plans"]} == {"p1"}
    assert {plan["id"] for plan in result["past"]} == {"extra-bound"}
    p1 = next(plan for plan in result["plans"] if plan["id"] == "p1")
    assert p1["activity"] == "running"
    assert p1["owner"] == "plan-owner"
    assert p1["model"] == "gpt-6-luna"
    assert p1["agent_id"] == "orch"
    assert [item["address"] for item in result["infrastructure"]] == [
        "main",
        "mailman",
        "planner",
    ]
    assert [item["paseo_id"] for item in result["infrastructure"]] == [
        "main-agent",
        "mail-agent",
        None,
    ]
    assert [agent["id"] for agent in result["agents"]] == ["builder", "unlabeled"]


def test_bound_plan_uses_real_paseo_agent_model_field(tmp_path):
    class CLI:
        def read_plan_status(self):
            return {"plans": [{"id": "p1", "status": "active"}]}

        def read_plan(self):
            return {"events": []}

        def read_plan_watch(self):
            return {"events": []}

        def read_address_bindings(self):
            return [{"address": "p1", "wake_context": {"paseo_id": "orch"}}]

        def read_messages(self):
            return []

        def read_plan_tasks(self, plan_id):
            return []

        def send(self, **kwargs):
            return {"id": "sent"}

    agents = [
        {
            "agent": {
                "id": "orch",
                "model": "claude-sonnet-5-5",
                "runtimeInfo": {"model": "claude-sonnet-5-5"},
            }
        }
    ]
    app = create_app(data_dir=tmp_path / "dash", cli=CLI(), agents=lambda: agents)

    result = _http_get(app, "/api/orchestrators")[1]

    assert result["plans"][0]["model"] == "claude-sonnet-5-5"


def test_orchestrator_row_does_not_join_by_plan_name_or_read_frontmatter():
    class CLI:
        def read_plan_summary(self, _plan_id):
            raise AssertionError("dashboard plan data must come from status/watch JSON")

    plans, _, _ = _plan_rows(
        {
            "plans": [
                {
                    "id": "2026-10-20-semble-compare",
                    "status": "active",
                    "title": "Semble comparison",
                    "assigned_to": "orchestrator-2",
                }
            ]
        },
        {"events": []},
        [],
        CLI(),
        [{"address": "semble-compare", "wake_context": {"paseo_id": "orch"}}],
        [{"agent": {"id": "orch", "status": "idle", "model": "gpt-6-luna"}}],
    )

    assert plans[0]["id"] == "semble-compare"
    assert plans[0]["plan_joined"] is False
    assert plans[0]["activity"] == "unknown"
    assert plans[0]["title"] == "orch semble-compare"


def test_unjoined_orchestrator_with_worker_uses_address_title():
    class CLI:
        def read_plan_summary(self, _plan_id):
            raise FileNotFoundError

    plans, _, _ = _plan_rows(
        {"plans": []},
        {"events": []},
        [],
        CLI(),
        [{"address": "ui-review", "wake_context": {"paseo_id": "orch"}}],
        [
            {"agent": {"id": "orch", "status": "idle", "title": "Wrong title"}},
            {
                "agent": {
                    "id": "worker",
                    "status": "running",
                    "labels": {"paseo.parent-agent-id": "orch"},
                }
            },
        ],
    )

    assert plans[0]["activity"] == "running"
    assert plans[0]["title"] == "orch ui-review"
    assert plans[0]["plan_joined"] is False


def test_open_question_count_clears_watch_notices_after_reply_or_closed_plan():
    messages = [
        {
            "from": "varde-watch",
            "kind": "needs-decision",
            "ts": "2026-10-21T09:00:00Z",
            "text": "Plan plan-one needs a decision",
        },
        {"from": "main", "to": "orch-one", "ts": "2026-10-21T09:01:00Z"},
        {
            "from": "varde-watch",
            "kind": "needs-user",
            "ts": "2026-10-21T09:02:00Z",
            "context": {"plan_id": "plan-one"},
        },
    ]
    assert _open_question_count(messages, "orch-one", "plan-one", {"questions": 1}) == 1
    assert _open_question_count(messages, "orch-one", "plan-one", {"questions": 0}) == 0
    assert (
        _open_question_count(messages, "orch-one", "plan-one", {"questions": []}) == 0
    )
    assert (
        _open_question_count(messages[:1] + messages[2:], "orch-one", "plan-one", {})
        == 2
    )


def test_open_question_count_keeps_direct_question_until_main_replies():
    messages = [
        {"from": "orch-one", "kind": "needs-user", "ts": "2026-10-21T09:00:00Z"},
        {"from": "main", "to": "orch-one", "ts": "2026-10-21T09:01:00Z"},
    ]
    assert _open_question_count(messages, "orch-one", "plan-one", {}) == 0
    assert _open_question_count(messages[:1], "orch-one", "plan-one", {}) == 1


def test_open_question_count_clears_dashboard_reply():
    messages = [
        {
            "from": "orch-one",
            "to": "main",
            "kind": "merge-ready",
            "ts": "2026-10-21T09:00:00Z",
        },
        {
            "from": "dashboard",
            "to": "orch-one",
            "kind": "info",
            "ts": "2026-10-21T09:01:00Z",
        },
    ]
    assert _open_question_count(messages, "orch-one", "plan-one", {}) == 0


def test_open_question_count_ignores_watcher_merge_ready():
    messages = [
        {
            "from": "varde-watch",
            "kind": "merge-ready",
            "ts": "2026-10-21T09:00:00Z",
            "context": {"plan_id": "plan-one"},
        },
    ]
    assert _open_question_count(messages, "orch-one", "plan-one", {"questions": 1}) == 0


def _infrastructure_with_relay(tmp_path, waiting_age_seconds):
    now = datetime.now(UTC)
    relay_path = tmp_path / ".cache" / "inbox" / "relay" / "state.json"
    relay_path.parent.mkdir(parents=True)
    relay_path.write_text(
        json.dumps(
            {
                "current_mailman": "mail-token",
                "events": [
                    {
                        "event": "waiting",
                        "at": (
                            now - timedelta(seconds=waiting_age_seconds)
                        ).isoformat(),
                        "token_id": "mail-token",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    bindings = [
        {
            "address": "mailman",
            "last_seen": (now - timedelta(hours=2)).isoformat(),
            "wake_context": {"paseo_id": "mailman-old"},
        },
        {
            "address": "mailman",
            "last_seen": (now - timedelta(minutes=1)).isoformat(),
            "wake_context": {"paseo_id": "mailman-new"},
        },
        {
            "address": "main",
            "last_seen": now.isoformat(),
            "wake_context": {"paseo_id": "gone-agent"},
        },
    ]
    agents = [
        {"agent": {"id": "mailman-old", "status": "idle", "title": "Old"}},
        {"agent": {"id": "mailman-new", "status": "running", "title": "Current"}},
    ]

    def unexpected_message_status():
        pytest.fail("orchestrator snapshot should use the listed agent status")

    _, infrastructure, _ = _plan_rows(
        {"plans": []},
        {"events": []},
        [],
        SimpleNamespace(
            read_message_status=unexpected_message_status,
            cwd=tmp_path,
            env={},
        ),
        bindings,
        agents,
    )
    return infrastructure


def test_infrastructure_uses_newest_live_binding_with_live_relay(tmp_path):
    main, mailman = _infrastructure_with_relay(tmp_path, 100)
    assert mailman["paseo_id"] == "mailman-new"
    assert mailman["status"] == "running"
    assert mailman["stale"] is False
    assert mailman["relay_alive"] is True
    assert main["paseo_id"] == "gone-agent"
    assert main["status"] == "unknown"
    assert main["stale"] is True


def test_infrastructure_marks_mailman_stale_when_relay_is_dead(tmp_path):
    _, mailman = _infrastructure_with_relay(tmp_path, 86400)
    assert mailman["paseo_id"] == "mailman-new"
    assert mailman["relay_alive"] is False
    assert mailman["status"] == "stale"
    assert mailman["stale"] is True


def test_agents_error_is_exposed_and_does_not_raise(tmp_path):
    def fail():
        raise ValueError("bad sidecar response")

    cli = type(
        "CLI",
        (),
        {
            "read_plan_status": lambda self: {"plans": []},
            "read_plan_watch": lambda self: {"events": []},
            "read_messages": lambda self: [],
            "read_plan": lambda self: {"events": []},
            "send": lambda self, **kwargs: {"id": "sent"},
        },
    )()
    app = create_app(data_dir=tmp_path / "dash", cli=cli, agents=fail)
    result = _http_get(app, "/api/orchestrators")[1]
    assert result["agents"] == []
    assert result["agents_error"] == "bad sidecar response"


def test_mailbox_exposes_counts_by_kind_and_state(tmp_path):
    class CLI:
        def read_plan(self):
            return {"events": []}

        def read_messages(self):
            return [
                {
                    "id": "decision",
                    "from": "builder",
                    "kind": "needs-user",
                    "text": "Choose",
                }
            ]

        def send(self, **kwargs):
            return {"id": "sent"}

    result = _http_get(
        create_app(data_dir=tmp_path / "dash", cli=CLI(), agents=list),
        "/api/mailbox",
    )[1]
    assert result["counts_by_kind_state"] == {"needs-user:pending": 1}


@pytest.mark.parametrize("status", ["cancelled", "abandoned"])
def test_concluded_plan_status_removes_pending_mailbox_item(tmp_path, status):
    class CLI:
        def read_plan(self):
            return {"plans": [{"id": "plan-one", "status": status}], "events": []}

        def read_plan_status(self):
            return {"plans": [{"id": "plan-one", "status": status}]}

        def read_address_bindings(self):
            return [{"address": "plan-one"}]

        def read_messages(self):
            return [
                {
                    "id": "question",
                    "from": "plan-one",
                    "kind": "needs-user",
                    "text": "Choose",
                }
            ]

        def send(self, **kwargs):
            return {"id": "sent"}

    response = _http_get(
        create_app(data_dir=tmp_path / "dashboard", cli=CLI(), agents=list),
        "/api/mailbox",
    )

    assert response[0] == 200
    assert response[1]["open"] == []


def test_durable_concluded_address_removes_mailbox_item(tmp_path):
    working_dir = tmp_path / "working"
    inbox_dir = working_dir / ".cache" / "inbox"
    inbox_dir.mkdir(parents=True)
    (inbox_dir / "messages.jsonl").write_text(
        json.dumps(
            {
                "id": "question",
                "ts": "2026-10-23T09:00:00Z",
                "from": "plan-one",
                "to": "main",
                "kind": "needs-user",
                "text": "Choose",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (inbox_dir / "state.json").write_text(
        json.dumps({"concluded_addresses": ["plan-one"]}), encoding="utf-8"
    )
    cli = VardeCLI(cwd=working_dir)
    cli.read_plan = lambda: {
        "plans": [{"id": "plan-one", "status": "active"}],
        "events": [],
    }
    cli.read_plan_status = lambda: {"plans": [{"id": "plan-one", "status": "active"}]}
    cli.read_address_bindings = lambda: [{"address": "plan-one"}]

    response = _http_get(
        create_app(data_dir=tmp_path / "dashboard", cli=cli, agents=list),
        "/api/mailbox",
    )

    assert response[0] == 200
    assert response[1]["open"] == []


def test_live_permission_is_projected_and_answered_with_paseo_request_id(
    tmp_path, monkeypatch
):
    calls = []

    class CLI:
        def read_plan(self):
            return {"events": []}

        def read_messages(self):
            return []

        def send(self, **kwargs):
            raise AssertionError("permission answer must not use mailbox send")

    class Plugin:
        async def respond_permission(self, session, request_id, decision):
            calls.append((session.provider, session.session_id, request_id, decision))

        async def close(self):
            return None

    plugin = Plugin()
    monkeypatch.setattr(
        PaseoPlugin, "from_environment", classmethod(lambda _cls: plugin)
    )
    agent_data = [
        {
            "agent": {
                "id": "paseo-agent-1",
                "title": "Builder",
                "pendingPermissions": [
                    {
                        "id": "permission-exec-42",
                        "name": "CodexBash",
                        "kind": "tool",
                        "title": "Run command: uv run pytest",
                        "description": "Run the runner tests",
                        "input": {"command": "uv run pytest", "cwd": "/tmp/work"},  # noqa: S108 - Fixture models the reported worktree path.
                        "detail": {
                            "type": "shell",
                            "command": "uv run pytest",
                            "cwd": "/tmp/work",  # noqa: S108 - Fixture models the reported worktree path.
                        },
                    }
                ],
            }
        }
    ]
    app = create_app(data_dir=tmp_path / "dash", cli=CLI(), agents=lambda: agent_data)

    class Supervisor:
        def approval_waits_for_mailbox(self):
            return []

        async def respond(self, session_id, request_id, decision, _harness=None):
            from varde_runner.plugins import SessionRef

            await plugin.respond_permission(
                SessionRef("codex", session_id), request_id, decision
            )
            return "responded"

    async def get_supervisor():
        return Supervisor()

    app.state.dashboard.supervisor_getter = get_supervisor
    mailbox = _http_get(app, "/api/mailbox")[1]
    permission = mailbox["permissions"][0]
    assert permission["msg_id"] == "perm:paseo-agent-1:permission-exec-42"
    assert permission["asked"] == "Run command: uv run pytest"
    assert permission["why"] == "Run the runner tests"
    assert permission["body"] == "uv run pytest\n/tmp/work"
    assert [option["id"] for option in permission["options"]] == ["allow", "deny"]
    detail = _http_get(app, f"/api/mailbox/{permission['msg_id']}")[1]
    assert detail["request_id"] == "permission-exec-42"
    answered = _http_request(
        app,
        f"/api/mailbox/{permission['msg_id']}/answer",
        method="POST",
        body={"option": "allow", "idempotency_key": "permission-key"},
    )
    assert answered[0] == 200
    assert answered[1]["status"] == "delivered"
    assert len(calls) == 1
    _, session_id, request_id, decision = calls[0]
    assert (session_id, request_id, decision) == (
        "paseo-agent-1",
        "permission-exec-42",
        "allow",
    )
    assert _http_get(app, "/api/mailbox")[1]["permissions"] == []


def test_dashboard_respond_uses_production_supervisor_wiring(tmp_path, monkeypatch):
    calls = []

    class Plugin:
        capabilities = RunnerCapabilities(respond=True)

        async def respond_permission(self, session, request_id, decision):
            calls.append((session.provider, session.session_id, request_id, decision))

        async def close(self):
            return None

    registry = PluginRegistry()
    registry.register("claude-sdk", Plugin(), provider_key="claude")
    monkeypatch.setattr("varde_runner.web.app.build_registry", lambda: registry)

    class CLI:
        def send(self, **_kwargs):
            return {"id": "sent"}

        def read_messages(self):
            return []

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "runner.toml").write_text(default_toml(), encoding="utf-8")
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(config_dir))
    app = create_app(data_dir=tmp_path / "dashboard", cli=CLI(), agents=list)
    dashboard = app.state.dashboard

    assert dashboard.supervisor_getter is not None

    async def respond():
        result = await dashboard.respond(
            "unmanaged-session", "permission-1", "allow", "claude-sdk"
        )
        await (await dashboard.supervisor_getter()).shutdown()
        return result

    result = asyncio.run(respond())

    assert result == "responded"
    assert calls == [("claude", "unmanaged-session", "permission-1", "allow")]


def test_api_get_requires_loopback_host(tmp_path):
    class CLI:
        def read_plan(self):
            return {"events": []}

        def read_messages(self):
            return []

        def send(self, **kwargs):
            return {"id": "sent"}

    app = create_app(data_dir=tmp_path / "dash", cli=CLI(), agents=list)
    status, payload = _http_get(app, "/api/mailbox", host="attacker.example:8000")
    assert status == 403
    assert payload["error"] == "invalid Host or Origin"


def test_mailbox_only_projects_open_decision_messages(tmp_path):
    notes = tmp_path / "context.json"
    notes.write_text(
        json.dumps(
            {
                "asked": "Choose an option",
                "why": "This blocks the build",
                "options": [{"label": "A", "consequence": "Continue"}],
                "recommendation": "A",
                "sources": ["plan-alpha"],
            }
        ),
        encoding="utf-8",
    )

    class CLI:
        def read_plan(self):
            return {"plans": [{"id": "builder", "status": "active"}], "events": []}

        def read_address_bindings(self):
            return [{"address": "builder"}]

        def read_messages(self):
            return [
                {
                    "id": "decision",
                    "from": "builder",
                    "kind": "needs-user",
                    "notes": str(notes),
                },
                {"id": "info", "from": "builder", "kind": "info", "text": "FYI"},
                {
                    "id": "blocked",
                    "from": "builder",
                    "kind": "blocked",
                    "text": "Old status",
                },
            ]

        def send(self, **kwargs):
            return {"id": "sent"}

    app = create_app(data_dir=tmp_path / "dashboard", cli=CLI(), agents=list)
    response = _http_get(app, "/api/mailbox")

    assert response[0] == 200
    assert [item["msg_id"] for item in response[1]["open"]] == ["decision"]
    assert response[1]["resolved"] == []


def test_mailbox_falls_back_to_message_and_capped_notes_text(tmp_path):
    notes = tmp_path / "question.md"
    notes.write_text("Real notes context " + "x" * 25_000, encoding="utf-8")

    class CLI:
        def read_plan(self):
            return {
                "plans": [{"id": "dashboard-usable", "status": "active"}],
                "events": [],
            }

        def read_address_bindings(self):
            return [{"address": "dashboard-usable"}]

        def read_messages(self):
            return [
                {
                    "id": "realistic-question",
                    "from": "dashboard-usable",
                    "kind": "needs-user",
                    "text": "Should this queue remain collapsed on mobile?",
                    "notes": str(notes),
                }
            ]

        def send(self, **kwargs):
            return {"id": "sent"}

    app = create_app(data_dir=tmp_path / "dashboard", cli=CLI(), agents=list)
    item = _http_get(app, "/api/mailbox")[1]["open"][0]

    assert item["needs_context"] is True
    assert item["body"] == "Should this queue remain collapsed on mobile?"
    assert item["notes_text"].startswith("Real notes context ")
    assert len(item["notes_text"]) == 20_000


@contextmanager
def _notes_text_projector(tmp_path):
    projector = InboxProjector(
        tmp_path / "notes-reader" / "inbox.sqlite3",
        read_messages=list,
        read_plan=lambda: {"events": []},
    )
    try:
        yield projector
    finally:
        projector.close()


def test_notes_text_reader_allows_document_suffixes_and_caps_text(tmp_path):
    with _notes_text_projector(tmp_path) as projector:
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        for suffix in (".md", ".json", ".txt"):
            notes = notes_dir / f"context{suffix}"
            notes.write_text("context " + "x" * 20_000, encoding="utf-8")
            text = projector._read_notes_text(str(notes))
            assert text.startswith("context ")
            assert len(text) == 20_000


def test_notes_text_reader_refuses_other_suffixes(tmp_path):
    with _notes_text_projector(tmp_path) as projector:
        private_pem = tmp_path / "private.pem"
        no_suffix = tmp_path / "secret"
        private_pem.write_text("private key text", encoding="utf-8")
        no_suffix.write_text("secret text", encoding="utf-8")

        assert projector._read_notes_text(str(private_pem)) == ""
        assert projector._read_notes_text(str(no_suffix)) == ""
        assert projector._read_notes_text("private.pem") == ""


def test_notes_text_reader_refuses_symlink_and_hidden_directory(tmp_path):
    with _notes_text_projector(tmp_path) as projector:
        visible = tmp_path / "visible.md"
        visible.write_text("visible notes", encoding="utf-8")
        link = tmp_path / "linked.md"
        link.symlink_to(visible)
        hidden_dir = tmp_path / ".private"
        hidden_dir.mkdir()
        hidden_notes = hidden_dir / "notes.md"
        hidden_notes.write_text("private notes", encoding="utf-8")

        assert projector._read_notes_text(str(link)) == ""
        assert projector._read_notes_text(str(hidden_notes)) == ""


def test_notes_text_reader_refuses_binary_file(tmp_path):
    with _notes_text_projector(tmp_path) as projector:
        binary = tmp_path / "binary.md"
        binary.write_bytes(b"\x89PNG\x00\xff")

        assert projector._read_notes_text(str(binary)) == ""


def test_notes_text_reader_caches_by_path_mtime_and_size(tmp_path, monkeypatch):
    with _notes_text_projector(tmp_path) as projector:
        notes = tmp_path / "context.md"
        notes.write_text("first", encoding="utf-8")
        original_open = Path.open
        opened = []

        def counted_open(path, *args, **kwargs):
            if path == notes:
                opened.append(path)
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", counted_open)
        assert projector._read_notes_text(str(notes)) == "first"
        assert projector._read_notes_text(str(notes)) == "first"
        assert opened == [notes]

        notes.write_text("changed size", encoding="utf-8")
        opened.clear()
        assert projector._read_notes_text(str(notes)) == "changed size"
        assert opened == [notes]

        notes.write_text("updated text", encoding="utf-8")
        metadata = notes.stat()
        os.utime(notes, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000_000))
        opened.clear()
        assert projector._read_notes_text(str(notes)) == "updated text"
        assert opened == [notes]


def test_mailbox_dismiss_audits_without_answer_or_ack(tmp_path):
    class CLI:
        def __init__(self):
            self.acknowledged = []

        def read_plan(self):
            return {"events": []}

        def read_messages(self):
            return [
                {
                    "id": "stale-message",
                    "from": "builder",
                    "kind": "needs-user",
                    "text": "Old question",
                }
            ]

        def send(self, **kwargs):
            raise AssertionError("dismiss must not send an answer")

        def acknowledge(self, message_id, *, address):
            self.acknowledged.append((message_id, address))

    cli = CLI()
    app = create_app(data_dir=tmp_path / "isolated-dashboard", cli=cli, agents=list)
    status, payload = _http_request(
        app, "/api/mailbox/stale-message/dismiss", method="POST", body={}
    )
    assert status == 200
    assert payload == {"dismissed": True, "msg_id": "stale-message"}
    assert cli.acknowledged == []
    mailbox = _http_get(app, "/api/mailbox")[1]
    assert mailbox["open"] == []
    assert mailbox["resolved"][0]["state"] == "dismissed"
    assert (
        app.state.decisions.db.execute("select count(*) from answers").fetchone()[0]
        == 0
    )


def test_mailbox_removes_legacy_non_decision_projection_rows(tmp_path):
    class CLI:
        def read_plan(self):
            return {"events": []}

        def read_messages(self):
            return [{"id": "old-info", "from": "builder", "kind": "info"}]

        def send(self, **kwargs):
            return {"id": "sent"}

    cli = CLI()
    projector = InboxProjector(
        tmp_path / "inbox.sqlite3",
        read_messages=cli.read_messages,
        read_plan=cli.read_plan,
    )
    projector.db.execute(
        "INSERT INTO inbox_projection(msg_id,payload) VALUES (?,?)",
        ("old-info", json.dumps({"msg_id": "old-info", "needs_context": False})),
    )
    projector.db.commit()

    projector.project()

    assert projector.row_count() == 0
    projector.close()


def test_mailbox_refreshes_legacy_decision_projection_metadata(tmp_path):
    notes = tmp_path / "decision.json"
    notes.write_text(
        json.dumps({"asked": "Choose", "why": "Blocking", "options": ["Go"]}),
        encoding="utf-8",
    )

    class CLI:
        def read_plan(self):
            return {"events": []}

        def read_messages(self):
            return [
                {
                    "id": "decision",
                    "from": "builder",
                    "kind": "needs-user",
                    "ts": "2026-10-19T10:00:00+00:00",
                    "notes": str(notes),
                }
            ]

        def send(self, **kwargs):
            return {"id": "sent"}

    cli = CLI()
    projector = InboxProjector(
        tmp_path / "inbox.sqlite3",
        read_messages=cli.read_messages,
        read_plan=cli.read_plan,
    )
    projector.db.execute(
        "INSERT INTO inbox_projection(msg_id,payload) VALUES (?,?)",
        (
            "decision",
            json.dumps(
                {"msg_id": "decision", "sender": "builder", "needs_context": False}
            ),
        ),
    )
    projector.db.commit()

    projector.project()

    payload = json.loads(
        projector.db.execute(
            "SELECT payload FROM inbox_projection WHERE msg_id='decision'"
        ).fetchone()[0]
    )
    assert payload["kind"] == "needs-user"
    assert payload["ts"] == "2026-10-19T10:00:00+00:00"
    projector.close()


def test_answer_http_validation_conflict_and_already_answered_cases(tmp_path):
    notes = tmp_path / "context.json"
    notes.write_text(
        json.dumps({"asked": "Choose", "why": "Blocking", "options": ["Go"]}),
        encoding="utf-8",
    )
    messages = [
        {"id": "q1", "from": "builder", "kind": "needs-user", "notes": str(notes)},
        {"id": "q2", "from": "planner", "kind": "needs-user", "notes": str(notes)},
    ]

    class CLI:
        def read_plan(self):
            return {"events": []}

        def read_messages(self):
            return messages

        def send(self, **kwargs):
            return {"id": "sent"}

    app = create_app(data_dir=tmp_path / "dash", cli=CLI(), agents=list)
    bad_option = _http_request(
        app,
        "/api/mailbox/q1/answer",
        method="POST",
        body={"option": "Nope", "idempotency_key": "bad-option"},
    )
    assert bad_option == (400, {"error": "option is not available"})
    too_long = _http_request(
        app,
        "/api/mailbox/q1/answer",
        method="POST",
        body={"text": "x" * 20_001, "idempotency_key": "too-long"},
    )
    assert too_long[0] == 413
    assert too_long[1]["status"] == "rejected"
    first = _http_request(
        app,
        "/api/mailbox/q1/answer",
        method="POST",
        body={"option": "Go", "idempotency_key": "same-key"},
    )
    assert first[0] == 200
    answered = _http_request(
        app,
        "/api/mailbox/q1/answer",
        method="POST",
        body={"option": "Go", "idempotency_key": "second-key"},
    )
    assert answered[0] == 409
    assert answered[1]["status"] == "already_answered"
    conflict = _http_request(
        app,
        "/api/mailbox/q2/answer",
        method="POST",
        body={"option": "Go", "idempotency_key": "same-key"},
    )
    assert conflict[0] == 409
    assert conflict[1]["status"] == "idempotency_conflict"


def test_real_http_and_isolated_varde_cli_deliver_option_and_free_text(
    tmp_path, runner_ui_built
):
    cli, notes, app = _real_cli_dashboard(tmp_path)
    with _running_http(app) as origin:
        with urllib.request.urlopen(  # noqa: S310 - Origin is the local HTTP test server.
            f"{origin}/", timeout=HTTP_TIMEOUT_SECONDS
        ) as response:
            page = response.read().decode()
            assert response.status == 200
            assert "Varde Runner" in page
        with urllib.request.urlopen(  # noqa: S310 - Origin is the local HTTP test server.
            f"{origin}/api/orchestrators", timeout=HTTP_TIMEOUT_SECONDS
        ) as response:
            plans = json.loads(response.read())["plans"]
            assert plans[0]["plan_id"] == "dashboard-plan"
            assert plans[0]["queue"][0]["status"] == "in_progress"
            assert plans[0]["last_message_age"] != "unknown"
        with urllib.request.urlopen(  # noqa: S310 - Origin is the local HTTP test server.
            f"{origin}/api/roles", timeout=HTTP_TIMEOUT_SECONDS
        ) as response:
            role_config = json.loads(response.read())["toml"]
        assert "[roles.orchestrator]" in role_config
        preview = _http_post(f"{origin}/api/roles/preview", {"toml": role_config})
        assert preview["preview_token"]
        saved = _http_post(
            f"{origin}/api/roles/save",
            {"toml": role_config, "preview_token": preview["preview_token"]},
        )
        assert saved["saved"] is True
        app.state.work_item_start = lambda item_id, notes_path, project: (
            "planner-session"
        )
        created = _http_post(
            f"{origin}/api/work-items",
            {
                "text": "Make a dashboard",
                "project": str(tmp_path),
                "idempotency_key": "dashboard-api",
            },
        )
        assert created["state"] == "planning"
        work_items = json.loads(
            urllib.request.urlopen(  # noqa: S310 - Origin is the local HTTP test server.
                f"{origin}/api/work-items", timeout=HTTP_TIMEOUT_SECONDS
            ).read()
        )
        assert work_items["work_items"][0]["id"] == created["id"]
        work_item = json.loads(
            urllib.request.urlopen(  # noqa: S310 - Origin is the local HTTP test server.
                f"{origin}/api/work-items/{created['id']}", timeout=HTTP_TIMEOUT_SECONDS
            ).read()
        )
        assert work_item["planner_session"] == "planner-session"
        assert work_item["audit"][0]["new_state"] == "new"

        message_id = _message_id(cli)
        detail = json.loads(
            urllib.request.urlopen(  # noqa: S310 - Origin is the local HTTP test server.
                f"{origin}/api/mailbox/{message_id}", timeout=HTTP_TIMEOUT_SECONDS
            ).read()
        )
        assert detail["context"]["asked"] == "Pick an answer"
        assert detail["recommendation"] == "Proceed"
        option = _http_post(
            f"{origin}/api/mailbox/{message_id}/answer",
            {"option": "Proceed", "idempotency_key": "option"},
        )
        assert option["status"] == "delivered"
        assert Path(option["notes_path"]).read_text(encoding="utf-8") == "Proceed"
        with urllib.request.urlopen(  # noqa: S310 - Origin is the local HTTP test server.
            f"{origin}/api/mailbox", timeout=HTTP_TIMEOUT_SECONDS
        ) as response:
            mailbox = json.loads(response.read())
        assert message_id not in [item["msg_id"] for item in mailbox["open"]]
        assert message_id in [item["msg_id"] for item in mailbox["resolved"]]
        sent = next(
            message
            for message in cli.read_messages()
            if message.get("notes") == option["notes_path"]
        )
        assert sent["to"] == "vrt-b1-builder"

        text = "🙂漢字\r\n" * 4000
        second_notes = notes.with_name("question-2.json")
        second_notes.write_text(notes.read_text(encoding="utf-8"), encoding="utf-8")
        cli.send(
            sender="vrt-b1-builder-2",
            recipient="dashboard",
            kind="needs-user",
            text="Explain",
            notes=str(second_notes),
        )
        second_id = _message_id(cli, "vrt-b1-builder-2")
        free_text = _http_post(
            f"{origin}/api/mailbox/{second_id}/answer",
            {"text": text, "idempotency_key": "free-text"},
        )
        assert free_text["status"] == "delivered"
        assert len(text) == 20_000
        assert Path(free_text["notes_path"]).read_bytes() == text.encode("utf-8")
        delivered = next(
            message
            for message in cli.read_messages()
            if message.get("notes") == free_text["notes_path"]
        )
        assert delivered["to"] == "vrt-b1-builder-2"


def _real_cli_dashboard(tmp_path):
    executable = shutil.which("varde")
    assert executable
    working = tmp_path / "working"
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "VARDE_CONFIG_DIR": str(tmp_path / "config"),
        "VARDE_WORKING_DIR": str(working),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
    }
    for name in ("home", "config", "working", "xdg-config", "xdg-cache", "xdg-data"):
        (tmp_path / name).mkdir(exist_ok=True)
    cli = VardeCLI(cwd=working, env=env)
    cli.read_address_bindings = lambda: [
        {
            "address": "dashboard-plan",
            "wake_context": {"paseo_id": "dashboard-agent"},
        }
    ]
    plan_dir = working / "plans" / "dashboard-plan"
    task_dir = plan_dir / "tasks"
    task_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        (
            "---\ntype: plan\nid: dashboard-plan\ntitle: Dashboard plan\n"
            "status: active\nowner: vrt-b1-orchestrator\n---\n"
        ),
        encoding="utf-8",
    )
    (task_dir / "B1.md").write_text(
        (
            "---\ntype: task\nid: dashboard-task\ntitle: Connect dashboard\n"
            "status: in_progress\n---\n"
        ),
        encoding="utf-8",
    )
    notes = tmp_path / "question.json"
    notes.write_text(
        json.dumps(
            {
                "asked": "Pick an answer",
                "why": "The orchestrator is blocked",
                "options": [{"label": "Proceed", "consequence": "Unblocks work"}],
                "recommendation": "Proceed",
                "sources": ["plan-alpha"],
            }
        ),
        encoding="utf-8",
    )
    cli.send(
        sender="vrt-b1-builder",
        recipient="dashboard",
        kind="needs-user",
        text="Pick one",
        notes=str(notes),
    )
    cli.send(
        sender="vrt-b1-orchestrator",
        recipient="dashboard",
        kind="info",
        text="Plan update",
        notes=str(notes),
    )
    app = create_app(data_dir=tmp_path / "dashboard", cli=cli, agents=list)
    app.state.dashboard.plan_reads = None
    cli.plan_reads = None
    return cli, notes, app


@contextmanager
def _running_http(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="off",
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    try:
        assert server.started
        yield f"http://127.0.0.1:{port}"
    finally:
        stop_server(server, thread)


def _message_id(cli, sender="vrt-b1-builder"):
    return next(
        message["id"]
        for message in cli.read_messages()
        if message.get("from") == sender and message.get("kind") == "needs-user"
    )


def _http_post(url, body):
    request = urllib.request.Request(  # noqa: S310 - Request URL comes from the local HTTP test server.
        url,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310 - Request targets the local HTTP test server.
        return json.loads(response.read())


def _http_get(app, path, *, host="localhost:8000"):
    return _http_request(app, path, host=host)


def _http_request(app, path, *, method="GET", body=None, host="localhost:8000"):
    import asyncio

    request_body = json.dumps(body).encode() if body is not None else b""

    async def dispatch():
        messages = []
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {
                "type": "http.request",
                "body": request_body,
                "more_body": False,
            }

        async def send(message):
            messages.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [
                    (b"host", host.encode()),
                    (b"content-type", b"application/json"),
                ],
                "client": ("127.0.0.1", 1234),
                "server": ("127.0.0.1", 8000),
            },
            receive,
            send,
        )
        body = b"".join(
            item.get("body", b"")
            for item in messages
            if item["type"] == "http.response.body"
        )
        return next(
            item["status"] for item in messages if item["type"] == "http.response.start"
        ), json.loads(body)

    return asyncio.run(dispatch())


def test_unbound_infrastructure_address_is_reported_missing():
    now = datetime.now(UTC)
    bindings = [
        {
            "address": "main",
            "last_seen": now.isoformat(),
            "wake_context": {"paseo_id": "main-agent"},
        }
    ]
    agents = [{"agent": {"id": "main-agent", "status": "running", "title": "Main"}}]

    _, infrastructure, _ = _plan_rows(
        {"plans": []}, {"events": []}, [], object(), bindings, agents
    )

    assert [(row["address"], row["status"]) for row in infrastructure] == [
        ("main", "running"),
        ("mailman", "missing"),
    ]
