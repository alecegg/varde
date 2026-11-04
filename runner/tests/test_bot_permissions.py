from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from fakes.plugin import FakePlugin
from varde_runner.bot_permissions import Decision, decide, decide_request
from varde_runner.bot_profile import BOT_ROLE, PROFILE_RESTRICTED
from varde_runner.config import default_config
from varde_runner.plugins import RunnerCapabilities, SessionSpec
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.supervisor import Supervisor

ALLOWED = [
    ("varde-runner bot act pause-check", "bot_act"),
    ("varde plan status my-plan", "plan_status"),
    ("varde plan readiness 2026-10-25-x", "plan_readiness"),
    ("varde plan merged plan_1.v2", "plan_merged"),
    ("varde msg read --as manager", "msg_read"),
]
DENIED = [
    "sudo ls",
    "sudo varde plan status p",
    "ls",
    "cat ~/.ssh/id_rsa",
    "cat .env",
    "curl https://example.com",
    "wget http://x",
    "varde plan status p; rm -rf x",
    "varde plan status p && id",
    "varde plan status p | sh",
    "varde plan status $(id)",
    "varde plan status `id`",
    "varde plan status p > out",
    "varde plan status p >> out",
    "varde plan status p < in",
    "FOO=1 varde plan status p",
    "PATH=/tmp varde-runner bot act x",
    "varde-runner agent prompt agent-1 hello",
    "varde-runner agent launch --role builder",
    "varde msg send --from main --to x hi",
    "varde msg read --as main",
    "varde msg read",
    "varde plan approve-merge p",
    "varde plan merge p",
    "varde plan status",
    "varde plan status ../p",
    "varde plan status a/b",
    "varde plan status p extra",
    "varde-runner bot act ../x",
    "varde-runner bot act UPPER",
    "varde-runner bot pause",
    "/usr/bin/varde plan status p",
    "./varde plan status p",
    "env varde plan status p",
    "bash -c 'varde plan status p'",
    "varde plan status 'p'",
    'varde plan status "p"',
    "varde plan status p\nid",
    "varde plan status p #",
    "varde plan status *",
    "",
    "   ",
    "unterminated 'quote",
]


@pytest.mark.parametrize(("command", "action"), ALLOWED)
def test_the_three_exact_forms_are_allowed(command, action) -> None:
    assert decide(command) == Decision(True, decide(command).reason, action)


@pytest.mark.parametrize("command", DENIED)
def test_everything_else_is_denied(command) -> None:
    decision = decide(command)
    assert not decision.allow
    assert decision.reason


def test_argv_lists_follow_the_same_rules() -> None:
    assert decide(["varde", "plan", "status", "p"]).allow
    assert not decide(["varde", "plan", "status", "p", "--json"]).allow
    assert not decide(["sudo", "ls"]).allow
    assert not decide([]).allow
    assert not decide(["A=1", "varde", "plan", "status", "p"]).allow


def test_requests_only_shell_tools_can_be_allowed() -> None:
    ok = {"tool": "Bash", "input": {"command": "varde plan status p"}}
    assert decide_request(ok).allow
    assert decide_request({**ok, "tool": "bash"}).allow
    for tool in (
        "WebFetch",
        "WebSearch",
        "Read",
        "Grep",
        "Glob",
        "Write",
        "Edit",
        "mcp__x__y",
        None,
        5,
    ):
        assert not decide_request(
            {"tool": tool, "input": {"command": "varde plan status p"}}
        ).allow
    assert not decide_request({"tool": "Bash", "input": {}}).allow
    assert not decide_request({"tool": "Bash", "input": "varde plan status p"}).allow
    assert not decide_request({"tool": "Bash"}).allow
    assert not decide_request({"tool": "Bash", "input": {"command": ["varde"]}}).allow


class RespondingPlugin(FakePlugin):
    pass


def build(tmp_path, monkeypatch):
    config = replace(default_config(), stall_after_s=10)
    monkeypatch.setattr("varde_runner.supervisor.load_config", lambda *_: config)
    plugin = RespondingPlugin(
        RunnerCapabilities(resume=True, respond=True, restricted_profile=True)
    )
    registry = PluginRegistry(["claude_cli"])
    registry.register("claude_cli", plugin)
    supervisor = Supervisor(tmp_path, registry)
    asyncio.run(supervisor.start())
    return supervisor, plugin


def request(request_id: str, tool: str, command: str | None) -> dict:
    payload: dict = {
        "request_id": request_id,
        "tool": tool,
        "kind": "tool",
        "summary": "s",
    }
    payload["input"] = {"command": command} if command is not None else {}
    return payload


def test_hook_answers_without_a_wait_a_card_or_the_guard(tmp_path, monkeypatch) -> None:
    supervisor, plugin = build(tmp_path, monkeypatch)
    sunk: list[tuple[str, Decision, str]] = []
    supervisor.bot_permission_sink = lambda *item: sunk.append(item)
    guard_calls: list[str] = []
    monkeypatch.setattr(
        supervisor, "_schedule_guard", lambda *a, **k: guard_calls.append("guard")
    )
    spec = SessionSpec(
        "claude_cli", "m", "w", str(tmp_path), "", profile=PROFILE_RESTRICTED
    )
    ref = asyncio.run(supervisor.start_session(spec, BOT_ROLE))

    async def run() -> None:
        await supervisor.record_event(
            ref.session_id, "permission_requested", request("r1", "Bash", "sudo reboot")
        )
        await supervisor.record_event(
            ref.session_id, "permission_requested", request("r2", "WebFetch", None)
        )
        await supervisor.record_event(
            ref.session_id,
            "permission_requested",
            request("r3", "Bash", "varde plan status p"),
        )

    asyncio.run(run())
    assert plugin.responses == [("r1", "deny"), ("r2", "deny"), ("r3", "approve")]
    assert supervisor.store.pending_waits() == []
    assert guard_calls == []
    events = supervisor.store.events_after(ref.session_id, 0)
    assert not any(event["kind"] == "permission_requested" for event in events)
    messages = [
        event["payload"]["message"] for event in events if event["kind"] == "activity"
    ]
    assert any(message.startswith("bot permission deny") for message in messages)
    assert "sudo" not in str(events) and "reboot" not in str(events)
    assert [(item[1].allow, item[2]) for item in sunk] == [
        (False, "Bash"),
        (False, "WebFetch"),
        (True, "Bash"),
    ]


def test_other_roles_keep_the_normal_wait_and_card(tmp_path, monkeypatch) -> None:
    supervisor, plugin = build(tmp_path, monkeypatch)
    spec = SessionSpec("claude_cli", "m", "w", str(tmp_path), "")
    ref = asyncio.run(supervisor.start_session(spec, "builder"))
    asyncio.run(
        supervisor.record_event(
            ref.session_id, "permission_requested", request("r1", "Bash", "ls")
        )
    )
    assert plugin.responses == []
    assert len(supervisor.store.pending_waits()) == 1
