from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest
from varde_runner.relay import (
    RelayCLI,
    RelayWorker,
    decide,
    result_for_send_error,
    urgent_delivery_action,
)
from varde_runner.store import SessionStore
from varde_runner.supervisor import SendOutcome


@pytest.mark.parametrize(
    ("action", "status", "expected"),
    [
        ({"wake": {}}, "idle", ("failed", "no-send")),
        ({"wake": {"paseo_id": "a"}}, "unknown", ("failed", "no-send")),
        ({"wake": {"paseo_id": "a"}}, "not-found", ("target-gone", "observed-result")),
        (
            {"wake": {"paseo_id": "a"}},
            RuntimeError("Agent not found"),
            ("target-gone", "observed-result"),
        ),
        (
            {"wake": {"paseo_id": "a"}},
            RuntimeError("Paseo agent session was not found"),
            ("target-gone", "observed-result"),
        ),
        (
            {"wake": {"paseo_id": "a"}},
            RuntimeError("sidecar offline"),
            ("failed", "no-send"),
        ),
        (
            {"wake": {"paseo_id": "a"}},
            RuntimeError("socket not found"),
            ("failed", "no-send"),
        ),
        ({"wake": {"paseo_id": "a"}}, "running", ("skipped-busy", "observed-result")),
        (
            {"wake": {"paseo_id": "a"}},
            {"status": "unknown", "archived": True},
            ("skipped-busy", "observed-result"),
        ),
        (
            {"wake": {"paseo_id": "a"}},
            {"status": "closed", "archived": True},
            "send",
        ),
        (
            {"wake": {"paseo_id": "a"}},
            {"status": "closed", "archived": False},
            ("skipped-busy", "observed-result"),
        ),
        (
            {"wake": {"paseo_id": "a"}},
            {"status": "idle", "archived": True},
            "send",
        ),
        ({"wake": {"paseo_id": "a"}, "prompt": "same"}, "idle", "send"),
    ],
)
def test_decide(action, status, expected):
    assert decide(action, status) == expected


def test_send_error_mapping():
    assert result_for_send_error(RuntimeError("Agent not found")) == (
        "target-gone",
        "observed-result",
    )


@pytest.mark.parametrize(
    ("caps", "urgent", "busy", "expected"),
    [
        (None, False, True, "skip"),
        (None, True, False, "send"),
        ({"steer": True, "interrupt": True}, True, True, "steer"),
        ({"interrupt": True}, True, True, "interrupt"),
        ({}, True, True, "queued"),
    ],
)
def test_urgent_delivery_action(caps, urgent, busy, expected):
    from types import SimpleNamespace

    capabilities = SimpleNamespace(**caps) if isinstance(caps, dict) else caps
    assert urgent_delivery_action(capabilities, urgent=urgent, busy=busy) == expected


@pytest.mark.parametrize(
    ("steer", "interrupt", "expected", "method"),
    [
        (True, True, ("pushed", "steer"), "send"),
        (False, True, ("pushed", "interrupt"), "send_with_interrupt"),
        (False, False, ("skipped-busy", "queued"), None),
    ],
)
def test_busy_urgent_delivery_uses_adapter_capability(
    steer, interrupt, expected, method
):
    class Registry:
        def capabilities(self, _harness):
            from varde_runner.plugins import RunnerCapabilities

            return RunnerCapabilities(steer=steer, interrupt=interrupt)

    class BusySupervisor:
        registry = Registry()

        def __init__(self):
            self.calls = []

        async def target_idle_status(self, _agent_id, _harness):
            return "running"

        async def send(self, *args, **kwargs):
            self.calls.append(("send", args, kwargs))
            return SendOutcome.SENT

        async def send_with_interrupt(self, *args, **kwargs):
            self.calls.append(("send_with_interrupt", args, kwargs))
            return SendOutcome.SENT

    supervisor = BusySupervisor()
    worker = RelayWorker(FakeCLI(), supervisor)
    urgent_action = {
        **action("urgent-action"),
        "urgent": True,
        "wake": {
            "agent_id": "agent-canonical",
            "session_id": "old-session",
            "harness": "codex-like",
        },
    }

    result = asyncio.run(worker.deliver(urgent_action))

    assert result == expected
    assert [call[0] for call in supervisor.calls] == ([method] if method else [])
    if method == "send_with_interrupt":
        _, args, kwargs = supervisor.calls[0]
        assert args[:3] == ("agent-canonical", urgent_action["prompt"], "codex-like")
        assert kwargs["request_id"] == "urgent-action"


def test_urgent_send_relay_and_show_delivered_as_steer(tmp_path, monkeypatch):
    import contextlib
    import io
    from datetime import UTC, datetime

    from varde_runner.plugins import RunnerCapabilities
    from varde_workflow.cli import _parser
    from varde_workflow.commands import msg, msg_show
    from varde_workflow.inbox import read_all, record_relay_event
    from varde_workflow.recipients import Resolved

    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)
    monkeypatch.setattr(
        msg,
        "_resolve_recipient",
        lambda _name, _working: Resolved("plan-a-builder", True, True),
    )
    args = _parser().parse_args(
        [
            "msg",
            "send",
            "--from",
            "main",
            "--to",
            "plan-a-builder",
            "--kind",
            "info",
            "--urgent",
            "please stop",
        ]
    )
    assert msg.run(args, working) == 0
    sent = read_all(working)[0]

    class Registry:
        def capabilities(self, _harness):
            return RunnerCapabilities(steer=True, interrupt=True)

    class BusySupervisor:
        registry = Registry()

        async def target_idle_status(self, _agent_id, _harness):
            return "running"

        async def send(self, *_args, **_kwargs):
            return SendOutcome.SENT

    worker = RelayWorker(FakeCLI(), BusySupervisor())
    result = asyncio.run(
        worker.deliver(
            {
                "action_id": "action-urgent",
                "urgent": True,
                "address": "plan-a-builder",
                "wake": {"agent_id": "agent-canonical", "harness": "codex-like"},
                "prompt": "delivery prompt",
            }
        )
    )
    assert result is not None
    assert result == ("pushed", "steer")
    record_relay_event(
        working,
        sent.id or "",
        sent.to,
        result[0],
        now=datetime.now(UTC),
        reason=result[1],
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert (
            msg_show.run(type("Args", (), {"id": sent.id, "json": False})(), working)
            == 0
        )
    assert "delivered-as: steer" in output.getvalue()


def test_takeover_queued_relay_send_is_accepted_without_retry():
    class QueuedSupervisor:
        async def target_idle_status(self, _agent_id, _harness=None):
            return "idle"

        async def send(self, *_args, **_kwargs):
            return SendOutcome.QUEUED

    cli = FakeCLI()
    worker = RelayWorker(cli, QueuedSupervisor())
    worker.identity = "identity"

    result = asyncio.run(worker.deliver(action()))

    assert result == ("pushed", "successful-send")
    assert cli.renewed == ["a"]
    assert result_for_send_error(RuntimeError("offline")) == (
        "failed",
        "observed-result",
    )


class FakeCLI:
    def __init__(self, *, status=None, bindings=None, waits=None):
        self.status_result = status or {"mailmen": []}
        self.bindings_result = list(bindings or [])
        self.waits = list(waits or [])
        self.confirmed = []
        self.confirm_harnesses = []
        self.ended = []
        self.renewed = []
        self.issued = 0
        self.sessions = []
        self.unbound = []
        self.confirm_error: Exception | None = None
        self.renew_result: dict[str, Any] = {"status": "renewed"}

    async def status(self):
        return self.status_result

    async def bindings(self):
        return self.bindings_result

    async def issue_and_bind(self, session):
        self.issued += 1
        self.sessions.append(session)
        return "identity"

    async def issue_and_bind_superseding(self, session):
        return await self.issue_and_bind(session)

    async def wait(self, identity):
        value = self.waits.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    async def confirm(self, action, result, evidence, identity, *, harness):
        self.confirm_harnesses.append(harness)
        if self.confirm_error:
            raise self.confirm_error
        self.confirmed.append((action, result, evidence))

    async def renew(self, action):
        self.renewed.append(action)
        return self.renew_result

    async def end(self, identity):
        self.ended.append(identity)

    async def unbind(self, session):
        self.unbound.append(session)


class FakePlugin:
    def __init__(self, status="idle", send_error=None):
        self.status = status
        self.send_error = send_error
        self.sent = []
        self.sent_harnesses = []
        self.request_ids = []

    async def idle_status(self, paseo_id):
        return self.status

    async def is_idle(self, session_id, harness=None):
        return self.status == "idle"

    async def target_idle_status(self, session_id, harness=None):
        return self.status

    async def inspect(self, paseo_id):
        return {"status": self.status, "archived": False}

    async def send(self, paseo_id, prompt, harness=None, *, request_id=None):
        if self.send_error:
            raise self.send_error
        if self.status != "idle":
            return SendOutcome.SKIPPED_BUSY
        self.sent.append((paseo_id, prompt))
        self.sent_harnesses.append(harness)
        self.request_ids.append(request_id)
        return SendOutcome.SENT


def action(action_id="a"):
    return {
        "action_id": action_id,
        "wake": {"paseo_id": "agent"},
        "prompt": "verbatim",
        "message_ids": ["m1"],
    }


def test_start_refuses_live_mailman():
    cli = FakeCLI(
        status={"mailmen": [{"id": "other", "alive": True}]},
        bindings=[
            {"address": "mailman", "session_id": "human-session", "token_id": "other"}
        ],
    )
    worker = RelayWorker(cli, FakePlugin())
    asyncio.run(asyncio.wait_for(worker.run(), timeout=5))
    assert worker.snapshot()["state"] == "refused"
    assert cli.ended == []


def test_start_refuses_live_mailman_from_runner_relay_status():
    cli = FakeCLI(
        status={"runner_relay": "up"},
        bindings=[
            {"address": "mailman", "session_id": "human-session", "token_id": "current"}
        ],
    )
    worker = RelayWorker(cli, FakePlugin())

    started = asyncio.run(worker._start_binding())

    assert started is False
    assert worker.snapshot()["state"] == "refused"
    assert cli.issued == 0


def test_successful_bind_clears_previous_refusal():
    cli = FakeCLI()
    worker = RelayWorker(cli, FakePlugin())
    worker.refusal = "old refusal"
    worker.last_error = "old error"

    asyncio.run(worker._start_binding())

    assert worker.refusal is None
    assert worker.last_error is None
    assert worker.session_id in cli.sessions


def test_failed_bind_does_not_claim_or_unbind_session():
    class FailedBindCLI(FakeCLI):
        async def issue_and_bind(self, session):
            raise RuntimeError("bind rejected")

    cli = FailedBindCLI()
    worker = RelayWorker(cli, FakePlugin())
    with pytest.raises(RuntimeError, match="bind rejected"):
        asyncio.run(worker._start_binding())

    asyncio.run(worker._release())

    assert worker.session_id is None
    assert cli.unbound == []


def test_superseded_stops_without_retry():
    cli = FakeCLI(waits=[{"actions": []}, RuntimeError("exit 64 superseded")])
    worker = RelayWorker(cli, FakePlugin(), sleep=lambda _: asyncio.sleep(0))
    asyncio.run(worker.run())
    assert worker.snapshot()["state"] == "stopped"
    assert cli.ended == ["identity"]


def test_wait_errors_back_off_and_recreate_rotates_identity():
    cli = FakeCLI(
        waits=[
            RuntimeError("temporary failure"),
            {"status": "none", "actions": [], "mailman": {"recreate": True}},
            RuntimeError("exit 64 superseded"),
            {"status": "none", "actions": []},
            RuntimeError("exit 64 superseded"),
        ]
    )
    delays = []

    async def sleep(delay):
        delays.append(delay)

    worker = RelayWorker(cli, FakePlugin(), sleep=sleep)
    asyncio.run(worker.run())
    assert delays == [30, 30]
    assert cli.issued == 2
    assert cli.ended == ["identity", "identity"]
    assert cli.sessions[0] != cli.sessions[1]


def test_action_delivery_deduplicates_and_preserves_prompt():
    cli = FakeCLI()
    plugin = FakePlugin()
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"

    async def deliver_twice():
        await worker._handle(action())
        await worker._handle(action())

    asyncio.run(deliver_twice())
    assert plugin.sent == [("agent", "verbatim")]
    assert cli.confirmed == [("a", "pushed", "successful-send")]
    assert cli.confirm_harnesses == ["unknown"]
    assert cli.renewed == ["a"]


def test_action_confirmation_uses_recipient_harness():
    cli = FakeCLI()
    worker = RelayWorker(cli, FakePlugin())
    worker.identity = "identity"
    native_action = {**action(), "wake": {"agent_id": "agent", "harness": "pi-rpc"}}

    asyncio.run(worker._handle(native_action))

    assert cli.confirm_harnesses == ["pi-rpc"]


def test_native_wake_sends_with_harness_and_agent_id_precedence():
    cli = FakeCLI()
    plugin = FakePlugin()
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"
    native_action = {
        **action(),
        "wake": {
            "harness": "claude",
            "agent_id": "native-agent",
            "paseo_id": "legacy-agent",
        },
    }

    assert asyncio.run(worker.deliver(native_action)) == (
        "pushed",
        "successful-send",
    )
    assert plugin.sent == [("native-agent", "verbatim")]
    assert plugin.sent_harnesses == ["claude"]
    assert plugin.request_ids == ["a"]


def test_wake_without_agent_id_fails_without_sending():
    cli = FakeCLI()
    plugin = FakePlugin()
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"

    assert asyncio.run(worker.deliver({**action(), "wake": {}})) == (
        "failed",
        "no-send",
    )
    assert plugin.sent == []


def test_send_exception_is_confirmed_and_isolated():
    cli = FakeCLI()
    worker = RelayWorker(cli, FakePlugin(send_error=RuntimeError("Agent not found")))
    worker.identity = "identity"
    asyncio.run(worker._handle(action()))
    assert cli.confirmed == [("a", "target-gone", "observed-result")]


def test_renew_precedes_status_check_and_send():
    events = []

    class OrderedCLI(FakeCLI):
        async def renew(self, action):
            events.append("renew")
            return await super().renew(action)

    class OrderedPlugin(FakePlugin):
        async def target_idle_status(self, session_id, harness=None):
            events.append("status")
            return await super().target_idle_status(session_id, harness)

        async def send(self, paseo_id, prompt, harness=None, *, request_id=None):
            events.append("send")
            return await super().send(paseo_id, prompt, harness)

    cli = OrderedCLI()
    worker = RelayWorker(cli, OrderedPlugin())
    worker.identity = "identity"
    asyncio.run(worker._handle(action()))
    assert events == ["renew", "status", "send"]


def test_confirm_failure_does_not_mark_action_confirmed():
    cli = FakeCLI()
    cli.confirm_error = RuntimeError("confirm failed")
    worker = RelayWorker(cli, FakePlugin())
    worker.identity = "identity"

    with pytest.raises(RuntimeError, match="confirm failed"):
        asyncio.run(worker._handle(action()))
    assert worker._confirmed == set()


def test_failed_pushed_confirm_retries_confirm_without_resending(tmp_path):
    cli = FakeCLI()

    class StoredFakePlugin(FakePlugin):
        store: SessionStore

    plugin = StoredFakePlugin()
    store = SessionStore(tmp_path)
    plugin.store = store
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"

    async def retry_confirmation():
        cli.confirm_error = RuntimeError("confirm failed")
        with pytest.raises(RuntimeError, match="confirm failed"):
            await worker._handle(action())
        cli.confirm_error = None
        await worker._handle(action())

    asyncio.run(retry_confirmation())
    assert plugin.sent == [("agent", "verbatim")]
    assert cli.confirmed == [("a", "pushed", "successful-send")]
    assert cli.renewed == ["a"]
    assert "a" in worker._confirmed
    wait = store.get_wait("wake:a")
    assert wait is not None and wait["decision"] == "pushed"
    store.close()


def test_expired_lease_is_not_confirmed():
    cli = FakeCLI()

    cli.renew_result = {"status": "expired"}
    worker = RelayWorker(cli, FakePlugin())
    worker.identity = "identity"
    asyncio.run(worker._handle(action()))
    assert cli.confirmed == []


def test_confirmation_dedup_is_bounded():
    worker = RelayWorker(FakeCLI(), FakePlugin())
    for index in range(1030):
        worker._record_confirmation(action(str(index)), str(index), "pushed")
    assert len(worker._confirmed) == 1024
    assert "0" not in worker._confirmed
    assert "1029" in worker._confirmed


def test_snapshot_reports_task_completion_and_exception():
    worker = RelayWorker(FakeCLI(), FakePlugin())

    async def fail():
        raise RuntimeError("relay stopped unexpectedly")

    async def exercise():
        worker.task = asyncio.create_task(fail())
        with suppress(RuntimeError):
            await worker.task

    asyncio.run(exercise())
    assert worker.snapshot()["task_done"] is True
    assert worker.snapshot()["task_exception"] == "relay stopped unexpectedly"


def test_busy_retry_uses_same_action():
    cli = FakeCLI()
    plugin = FakePlugin(status="running")
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"
    item = action()
    asyncio.run(worker._handle(item))
    plugin.status = "idle"
    asyncio.run(worker._handle(item))
    assert cli.confirmed == [
        ("a", "skipped-busy", "observed-result"),
        ("a", "pushed", "successful-send"),
    ]


def test_initial_exit_64_retries_but_later_exit_64_stops():
    cli = FakeCLI(
        waits=[
            RuntimeError("exit 64"),
            {"actions": []},
            RuntimeError("superseded: exit 64"),
        ]
    )
    delays = []

    async def sleep(delay):
        delays.append(delay)

    worker = RelayWorker(cli, FakePlugin(), sleep=sleep)
    asyncio.run(worker.run())
    assert delays == [30]
    assert worker.state == "stopped"


def test_startup_error_is_recorded_and_retried():
    class StartupErrorCLI(FakeCLI):
        calls = 0

        async def status(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("status unavailable")
            return await super().status()

    cli = StartupErrorCLI(waits=[{"actions": []}, RuntimeError("superseded")])
    delays = []

    async def sleep(delay):
        delays.append(delay)

    worker = RelayWorker(cli, FakePlugin(), sleep=sleep)
    asyncio.run(worker.run())
    assert delays == [30]
    assert worker.failures[0]["error"] == "status unavailable"


def test_relay_cli_kills_wait_process_on_cancel(monkeypatch):
    started = asyncio.Event()

    class Process:
        returncode = None
        killed = False
        waited = False

        async def communicate(self):
            started.set()
            await asyncio.Future()

        def kill(self):
            self.killed = True

        async def wait(self):
            self.waited = True

    process = Process()

    async def create_process(*_args, **_kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    cli = RelayCLI(cwd=Path("."))

    async def exercise():
        task = asyncio.create_task(cli.run("msg", "relay", "--wait"))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert process.killed and process.waited
