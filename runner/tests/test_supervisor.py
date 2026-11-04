import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from varde_runner.config import Role
from varde_runner.events import RunnerEvent
from varde_runner.guard_policy import allowlist as guard_allowlist
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSpec
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.relay import RelayCLIProtocol, RelayWorker
from varde_runner.store import SessionStore
from varde_runner.supervisor import SendOutcome, Supervisor
from varde_runner.waits import approval_wait_id


@dataclass
class FakePlugin:
    capabilities: RunnerCapabilities
    pid_file: str
    prompt_file: str
    send_entered: asyncio.Event | None = None
    send_release: asyncio.Event | None = None
    close_calls: int = 0
    started_spec: SessionSpec | None = None

    async def start(self, spec):
        self.started_spec = spec
        child = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(60)"
        )
        await asyncio.to_thread(Path(self.pid_file).write_text, str(child.pid))
        return SessionRef("fake", "session-1")

    async def resume(self, ref):
        return ref

    async def send(self, ref, prompt):
        if self.send_entered:
            self.send_entered.set()
        if self.send_release:
            await self.send_release.wait()
        path = Path(self.prompt_file)
        previous = await asyncio.to_thread(path.read_text) if path.exists() else ""
        await asyncio.to_thread(path.write_text, previous + prompt + "\n")

    async def events(self, ref):
        if False:
            yield RunnerEvent("status", "session-1")

    async def respond_permission(self, ref, request_id, decision):
        return None

    async def stop(self, ref):
        return None

    async def close(self):
        self.close_calls += 1


def test_supervisor_closes_a_shared_plugin_once(tmp_path):
    backend = plugin(tmp_path)
    supervisor = Supervisor(
        tmp_path,
        {"codex": backend, "pi": backend, "claude": backend},
    )

    asyncio.run(supervisor.shutdown())

    assert backend.close_calls == 1


def test_supervisor_accepts_plugin_registry(tmp_path):
    backend = plugin(tmp_path)
    registry = PluginRegistry()
    registry.register("fake-harness", backend, provider_key="fake-provider")
    supervisor = Supervisor(tmp_path, registry)

    session = asyncio.run(
        supervisor.start_session(
            SessionSpec("fake-provider", "model", "workspace", str(tmp_path)),
            "planner",
        )
    )

    assert session.provider == "fake"
    assert backend.started_spec is not None
    assert backend.started_spec.role == "planner"
    asyncio.run(supervisor.shutdown())


@pytest.mark.parametrize("kind", ["session_end", "status"])
def test_nonterminal_events_keep_binding_and_terminal_events_remove_it(
    tmp_path, monkeypatch, kind
):
    backend = plugin(tmp_path)
    supervisor = Supervisor(tmp_path, {"fake": backend})
    unbound = []

    class Addresses:
        def unbind(self, remote_id, _now):
            unbound.append(remote_id)

    from types import SimpleNamespace

    monkeypatch.setattr(
        "varde_data.open.open_data",
        lambda *_args: SimpleNamespace(addresses=Addresses()),
    )

    async def run():
        session = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        supervisor.register_address_binding(session.session_id, tmp_path, "remote")
        payload = {"status": "failed"} if kind == "session_end" else {"status": "error"}
        await supervisor.record_event(session.session_id, kind, payload)
        assert supervisor.store.get_address_binding(session.session_id) is not None
        assert unbound == []
        terminal_payload = {**payload, "terminal": True}
        await supervisor.record_event(session.session_id, kind, terminal_payload)
        assert supervisor.store.get_address_binding(session.session_id) is None
        assert unbound == ["remote"]

    asyncio.run(run())
    supervisor.store.close()


def _enable_guard_config(monkeypatch):
    role = Role("claude-sdk", "sonnet", "medium", "read-only", ())
    config = SimpleNamespace(guard=lambda: role, max_no_progress_restarts=3)
    monkeypatch.setattr("varde_runner.supervisor.load_config", lambda *_args: config)
    return role


def test_guard_approval_is_logged_and_does_not_answer_human_decision(
    tmp_path, monkeypatch
):
    _enable_guard_config(monkeypatch)
    supervisor = Supervisor(tmp_path, {})
    supervisor.store.upsert_workspace(
        "workspace", repo_root=str(tmp_path), cwd=str(tmp_path)
    )
    supervisor.store.create_session(
        "session", "fake", {"session_id": "remote"}, "builder", workspace_id="workspace"
    )
    request_id = "guarded-request"
    decision_id = approval_wait_id("session", request_id)
    supervisor.store.record_decision_event(
        decision_id, request_key="command_prefix:pytest", response=None
    )
    for human_id in ("human-1", "human-2"):
        supervisor.store.record_decision_event(
            human_id, request_key="command_prefix:pytest", response="approve"
        )
    supervisor.store.create_wait(
        decision_id,
        "session",
        "approval",
        payload={"request_id": request_id},
    )
    monkeypatch.setattr(
        "varde_runner.supervisor.evaluate_guard",
        lambda *_args: {
            "verdict": "approve",
            "reason": "confirmed",
            "request_key": "command_prefix:pytest",
        },
    )

    async def responded(_session_id, answered_request_id, _decision):
        await supervisor.record_event(
            "session",
            "permission_resolved",
            {
                "request_id": answered_request_id,
                "decision": "approve",
                "guarded": True,
            },
        )
        return "responded"

    monkeypatch.setattr(supervisor, "respond", responded)
    asyncio.run(
        supervisor._run_guard("session", request_id, {"command": "pytest tests"})
    )

    verdict = supervisor.store.guard_verdict_for("session", request_id)
    assert verdict is not None
    assert verdict["verdict"] == "approve"
    asyncio.run(
        supervisor.record_event(
            "session",
            "permission_resolved",
            {"request_id": request_id, "decision": "approve"},
        )
    )
    guard_event = next(
        row
        for row in supervisor.store.decision_events()
        if row["request_id"] == decision_id
    )
    assert guard_event["response"] is None
    supervisor._guard_approval_responses.clear()
    supervisor._backfill_approval_waits()
    guard_event = next(
        row
        for row in supervisor.store.decision_events()
        if row["request_id"] == decision_id
    )
    assert guard_event["response"] is None
    assert guard_allowlist(supervisor.store.decision_events()) == []
    supervisor.store.close()


def test_guard_missing_session_records_escalation(tmp_path, monkeypatch):
    _enable_guard_config(monkeypatch)
    supervisor = Supervisor(tmp_path, {})

    asyncio.run(
        supervisor._run_guard("missing-session", "request", {"command": "pytest"})
    )

    verdict = supervisor.store.guard_verdict_for("missing-session", "request")
    assert verdict is not None
    assert verdict["verdict"] == "escalate"
    assert verdict["reason"] == "permission session is missing"
    supervisor.store.close()


def test_guard_retries_failed_verdict_write_as_escalation(tmp_path, monkeypatch):
    _enable_guard_config(monkeypatch)
    supervisor = Supervisor(tmp_path, {})
    original_record = supervisor.store.record_guard_verdict
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("temporary database failure")
        return original_record(*args, **kwargs)

    monkeypatch.setattr(supervisor.store, "record_guard_verdict", fail_once)

    asyncio.run(
        supervisor._run_guard("missing-session", "request", {"command": "pytest"})
    )

    verdict = supervisor.store.guard_verdict_for("missing-session", "request")
    assert calls == 2
    assert verdict is not None
    assert verdict["verdict"] == "escalate"
    assert verdict["reason"] == "guard verdict recording failed"
    supervisor.store.close()


def test_guard_window_timeout_records_escalation(tmp_path, monkeypatch):
    _enable_guard_config(monkeypatch)
    supervisor = Supervisor(tmp_path, {})
    supervisor.store.upsert_workspace(
        "workspace", repo_root=str(tmp_path), cwd=str(tmp_path)
    )
    supervisor.store.create_session(
        "session", "fake", {"session_id": "remote"}, "builder", workspace_id="workspace"
    )

    async def timed_out(awaitable, **_kwargs):
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("varde_runner.supervisor.asyncio.wait_for", timed_out)

    asyncio.run(supervisor._run_guard("session", "request", {"command": "pytest"}))

    verdict = supervisor.store.guard_verdict_for("session", "request")
    assert verdict is not None
    assert verdict["verdict"] == "escalate"
    assert verdict["reason"] == "guard timed out"
    supervisor.store.close()


def test_enabled_guard_reschedules_pending_permission(tmp_path, monkeypatch):
    supervisor = Supervisor(tmp_path, {})
    supervisor.store.create_session(
        "session", "fake", {"session_id": "remote"}, "builder"
    )
    supervisor.store.create_wait(
        approval_wait_id("session", "request"),
        "session",
        "approval",
        payload={"request_id": "request"},
    )
    monkeypatch.setattr(supervisor, "guard_enabled", lambda: True)
    scheduled = []
    monkeypatch.setattr(
        supervisor,
        "_schedule_guard",
        lambda *args: scheduled.append(args),
    )

    supervisor._reschedule_pending_guards()

    assert scheduled == [("session", "request", {"request_id": "request"})]
    supervisor.store.close()


def test_restart_guard_scheduling_rechecks_pending_waits(tmp_path, monkeypatch):
    _enable_guard_config(monkeypatch)
    supervisor = Supervisor(tmp_path, {})
    supervisor.store.create_session(
        "session", "fake", {"session_id": "remote"}, "builder"
    )
    supervisor.store.create_wait(
        approval_wait_id("session", "request"),
        "session",
        "approval",
        payload={"request_id": "request"},
    )
    scheduled = []
    monkeypatch.setattr(
        supervisor,
        "_schedule_guard",
        lambda *args: scheduled.append(args),
    )

    async def restart():
        await supervisor.start()
        assert scheduled == [("session", "request", {"request_id": "request"})]
        await supervisor.shutdown()

    asyncio.run(restart())


def test_supervisor_resolves_paseo_provider_name_as_wake_harness(tmp_path):
    class UnmanagedClaude:
        capabilities = RunnerCapabilities(idle_status=True)

        def __init__(self):
            self.sent = []

        async def idle_status(self, ref):
            assert ref.provider == "claude"
            return "idle"

        async def send(self, ref, prompt):
            self.sent.append((ref.session_id, prompt))

    backend = UnmanagedClaude()
    registry = PluginRegistry()
    registry.register("claude-sdk", backend, provider_key="claude")
    supervisor = Supervisor(tmp_path, registry)

    class RelayCommand:
        async def renew(self, action_id):
            return {"status": "renewed"}

    worker = RelayWorker(cast("RelayCLIProtocol", RelayCommand()), supervisor)
    outcome = asyncio.run(
        worker.deliver(
            {
                "action_id": "action-1",
                "wake": {"harness": "claude", "paseo_id": "paseo-agent"},
                "prompt": "wake prompt",
            }
        )
    )

    assert outcome == ("pushed", "successful-send")
    assert backend.sent == [("paseo-agent", "wake prompt")]


def plugin(tmp_path, *, persistent=True, resume=True, idle=True):
    return FakePlugin(
        RunnerCapabilities(
            resume=resume, idle_status=idle, persistent_process=persistent
        ),
        str(tmp_path / "child.pid"),
        str(tmp_path / "prompts.txt"),
    )


def test_killed_ipc_client_leaves_child_and_session_available(
    tmp_path, require_unix_socket
):
    async def run():
        backend = plugin(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": backend})
        await supervisor.start()
        session = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "planner"
        )
        socket_path = tmp_path.parents[2] / f"varde-{uuid4().hex[:8]}.sock"
        await supervisor.start_ipc(socket_path)
        assert socket_path.stat().st_mode & 0o777 == 0o600
        client_script = """
import asyncio, json, socket, sys
async def main():
    reader, writer = await asyncio.open_unix_connection(sys.argv[1])
    writer.write(
        (json.dumps({"op":"get_session", "session_id":sys.argv[2]}) + "\\n").encode()
    )
    await writer.drain()
    print(await reader.readline(), flush=True)
    await asyncio.Event().wait()
asyncio.run(main())
"""
        client = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            client_script,
            str(socket_path),
            session.session_id,
            stdout=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONPATH": "runner/src"},
        )
        try:
            assert client.stdout is not None
            output = await client.stdout.readline()
            assert session.session_id.encode() in output
            client.send_signal(signal.SIGKILL)
            await asyncio.wait_for(client.wait(), timeout=5)
            os.kill(int((tmp_path / "child.pid").read_text()), 0)

            reader, writer = await asyncio.open_unix_connection(socket_path)
            writer.write(
                (
                    f'{{"op":"get_session","session_id":"{session.session_id}"}}\n'
                ).encode()
            )
            await writer.drain()
            state = await reader.readline()
            assert b'"role": "planner"' in state
            writer.close()
            await writer.wait_closed()
        finally:
            if client.returncode is None:
                client.kill()
                await asyncio.wait_for(client.wait(), timeout=5)
            await supervisor.shutdown()
            os.kill(int((tmp_path / "child.pid").read_text()), signal.SIGTERM)

    asyncio.run(run())


@pytest.mark.parametrize("can_resume,expected", [(True, "running"), (False, "error")])
def test_sigkill_restart_reconciles_without_resending_prompt(
    tmp_path, can_resume, expected
):
    script = """
import asyncio, sys
from pathlib import Path
from test_supervisor import plugin
from varde_runner.plugins import SessionSpec
from varde_runner.supervisor import Supervisor

async def main(directory):
    root = Path(directory)
    backend = plugin(root, persistent=True, resume=True)
    supervisor = Supervisor(root, {"fake": backend})
    await supervisor.start()
    session = await supervisor.start_session(
        SessionSpec("fake", "model", "workspace", directory), "planner"
    )
    await supervisor.record_event(session.session_id, "status", {"status": "idle"})
    await supervisor.send(session.session_id, "once")
    (root / "session.id").write_text(session.session_id)
    await asyncio.Event().wait()

asyncio.run(main(sys.argv[1]))
"""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(["runner/src", "runner/tests"])}
    process = subprocess.Popen([sys.executable, "-c", script, str(tmp_path)], env=env)  # noqa: S603 - Test starts a controlled child interpreter for the supervisor.
    try:
        ready = tmp_path / "session.id"
        deadline = time.monotonic() + 10
        while not ready.exists() and process.poll() is None:
            if time.monotonic() > deadline:
                pytest.fail("supervisor subprocess did not become ready")
            time.sleep(0.02)
        assert ready.exists()
        process.send_signal(signal.SIGKILL)
        process.wait(timeout=5)
        os.kill(int((tmp_path / "child.pid").read_text()), 0)

        async def restart():
            backend = plugin(tmp_path, persistent=True, resume=can_resume)
            supervisor = Supervisor(tmp_path, {"fake": backend})
            await supervisor.start()
            session_id = ready.read_text()
            session = supervisor.store.get_session(session_id)
            assert session is not None
            assert session["status"] == expected
            assert supervisor.idle_status(session_id) == "unknown"
            if can_resume:
                assert (
                    await supervisor.send(session_id, "must not be duplicated")
                ).value == "skipped_busy"
            else:
                assert (
                    await supervisor.send(session_id, "must not be duplicated")
                ).value == "failed"
            assert (tmp_path / "prompts.txt").read_text().splitlines() == ["once"]
            await supervisor.shutdown()

        asyncio.run(restart())
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        pid_file = tmp_path / "child.pid"
        if pid_file.exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pid_file.read_text()), signal.SIGTERM)


def test_unknown_idle_status_refuses_send(tmp_path):
    async def run():
        supervisor = Supervisor(tmp_path, {"fake": plugin(tmp_path, idle=False)})
        await supervisor.start()
        session = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "planner"
        )
        assert supervisor.idle_status(session.session_id) == "unknown"
        assert (
            await supervisor.send(session.session_id, "blocked")
        ).value == "skipped_busy"
        await supervisor.shutdown()

    asyncio.run(run())


def test_concurrent_sends_claim_idle_session_once(tmp_path):
    async def run():
        backend = plugin(tmp_path)
        backend.send_entered = asyncio.Event()
        backend.send_release = asyncio.Event()
        supervisor = Supervisor(tmp_path, {"fake": backend})
        await supervisor.start()
        session = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "planner"
        )
        await supervisor.record_event(session.session_id, "status", {"status": "idle"})
        first = asyncio.create_task(supervisor.send(session.session_id, "first"))
        await backend.send_entered.wait()
        second = asyncio.create_task(supervisor.send(session.session_id, "second"))
        backend.send_release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        assert cast("SendOutcome", results[0]) == SendOutcome.SENT
        assert cast("SendOutcome", results[1]) == SendOutcome.SKIPPED_BUSY
        assert (tmp_path / "prompts.txt").read_text().splitlines() == ["first"]
        await supervisor.shutdown()
        os.kill(int((tmp_path / "child.pid").read_text()), signal.SIGTERM)

    asyncio.run(run())


def test_watcher_resumes_after_last_sequence_and_logs_failure(tmp_path, caplog):
    class CursorPlugin(FakePlugin):
        seen_sequence = None

        async def events_after(self, ref, after_sequence):
            self.seen_sequence = after_sequence
            raise OSError("event stream failed")
            yield None

    async def run():
        store = SessionStore(tmp_path)
        store.create_session(
            "s1", "fake", {"provider": "fake", "session_id": "remote"}, "planner"
        )
        store.append_event("s1", "text", {"text": "saved"})
        store.close()
        backend = CursorPlugin(RunnerCapabilities(resume=True), "", "")
        supervisor = Supervisor(tmp_path, {"fake": backend})
        await supervisor.start()
        await asyncio.sleep(0)
        assert backend.seen_sequence == 1
        await asyncio.sleep(0)
        session = supervisor.store.get_session("s1")
        assert session is not None
        assert session["status"] == "error"
        assert "event stream failed" in caplog.text
        await supervisor.shutdown()

    asyncio.run(run())
