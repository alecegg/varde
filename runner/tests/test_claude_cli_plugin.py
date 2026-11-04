import asyncio
import json
import os
import signal
import time
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from varde_runner.events import RunnerEvent
from varde_runner.plugins import SessionRef, SessionSpec
from varde_runner.plugins.claude_cli.plugin import (
    ClaudeCliPlugin,
    ProcessIdentity,
    child_env,
)
from varde_runner.protocol import ResumeSettings

FAKE = Path(__file__).parent / "fakes" / "fake_claude.py"
REMOVED = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")


async def next_kind(events, kind, timeout=2):
    async def find():
        async for event in events:
            if event.kind == kind:
                return event
        raise AssertionError(f"stream ended before {kind}")

    return await asyncio.wait_for(find(), timeout)


def make_plugin(tmp_path, **kwargs):
    kwargs.setdefault("state_dir", tmp_path / "state")
    kwargs.setdefault(
        "process_inspector",
        lambda _pid, command: ProcessIdentity("test-start", " ".join(command)),
    )
    return ClaudeCliPlugin(FAKE, **kwargs)


def test_process_alive_tracks_returncode(tmp_path):
    plugin = make_plugin(tmp_path)
    ref = SessionRef("claude-cli", "session-1")
    process = SimpleNamespace(returncode=None)
    plugin._processes[ref.session_id] = cast("asyncio.subprocess.Process", process)
    assert plugin.process_alive(ref)
    process.returncode = 0
    assert not plugin.process_alive(ref)


def test_large_stdout_and_stderr_lines_are_drained(tmp_path, monkeypatch):
    async def exercise():
        monkeypatch.setenv("FAKE_CLAUDE_LARGE_LINES", "1")
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("claude-cli", "model", "workspace-1", str(tmp_path))
        )
        stderr_lines = plugin._stderr[ref.session_id]
        events = plugin.events(ref)
        try:
            event = await next_kind(events, "status")
            assert event.payload["status"] == "idle"
            await asyncio.wait_for(plugin._readers[ref.session_id], 30)
            assert list(stderr_lines) == [
                "y" * (1024 * 1024),
                "stderr-followup",
            ]
        finally:
            await plugin.close()
            await events.aclose()

    asyncio.run(exercise())


def test_oversized_stdout_line_reports_error_without_reader_crash(
    tmp_path, monkeypatch
):
    async def exercise():
        monkeypatch.setenv("FAKE_CLAUDE_OVERSIZED_LINES", "1")
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("claude-cli", "model", "workspace-1", str(tmp_path))
        )
        stderr_lines = plugin._stderr[ref.session_id]
        events = plugin.events(ref)
        try:
            error = await next_kind(events, "error", timeout=10)
            assert "stdout line exceeded the reader limit" in error.payload["message"]
            await asyncio.wait_for(plugin._readers[ref.session_id], 10)
            assert any(
                "stderr line exceeded the 16 MiB reader limit" in item
                for item in stderr_lines
            )
        finally:
            await plugin.close()
            await events.aclose()

    asyncio.run(exercise())


def test_oversized_stdout_line_does_not_drop_later_events(tmp_path, monkeypatch):
    async def exercise():
        monkeypatch.setenv("FAKE_CLAUDE_OVERSIZED_THEN_EVENT", "1")
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("claude-cli", "model", "workspace-1", str(tmp_path))
        )
        events = plugin.events(ref)
        try:
            error = await next_kind(events, "error", timeout=10)
            assert "stdout line exceeded the reader limit" in error.payload["message"]
            status = await next_kind(events, "status", timeout=10)
            assert status.payload["status"] == "idle"
            assert plugin.process_alive(ref)
        finally:
            await plugin.close()
            await events.aclose()

    asyncio.run(exercise())


def test_start_send_events_permission_interrupt_and_environment(tmp_path, monkeypatch):
    async def exercise():
        for name in REMOVED:
            monkeypatch.setenv(name, "must-not-leak")
        plugin = make_plugin(tmp_path)
        spec = SessionSpec(
            "claude-cli",
            "model",
            "workspace-1",
            str(tmp_path),
            mode_id="auto",
            agent_id="runner-agent",
        )
        assert child_env(spec)["VARDE_AGENT_ID"] == "runner-agent"
        ref = await plugin.start(spec)
        events = plugin.events(ref)
        try:
            env_event = await next_kind(events, "text")
            env = json.loads(env_event.payload["text"])
            assert env == {
                "agent": "runner-agent",
                "harness": "claude-cli",
                "state_events": "1",
                "stripped": True,
            }
            permission = await next_kind(events, "permission_requested")
            assert permission.payload["tool_use_id"] == "tool-1"
            assert "input" not in permission.payload
            assert "private-input" not in str(permission)

            await plugin.respond_permission(ref, "stale-id", "allow")
            denied = json.loads((await next_kind(events, "text")).payload["text"])
            assert denied == {"behavior": "deny", "message": "Permission denied"}
            await plugin.respond_permission(ref, "permit-1", "allow")
            await plugin.respond_permission(ref, "permit-1", "deny")
            allowed = json.loads((await next_kind(events, "text")).payload["text"])
            assert allowed["behavior"] == "allow"
            assert allowed["updatedInput"] == {"command": "echo private-input"}

            await plugin.send(ref, "hello")
            assert (await next_kind(events, "text")).payload["text"] == "hello"
            tool_intent = await next_kind(events, "tool_intent")
            assert "input" not in tool_intent.payload["raw"]
            assert "hidden-tool-args" not in str(tool_intent)
            await asyncio.wait_for(plugin.interrupt(ref), 3)
            assert await plugin.idle_status(ref) == "idle"
        finally:
            await plugin.close()
            await events.aclose()
        persisted = json.loads(
            plugin._spec_path(ref.session_id).read_text(encoding="utf-8")
        )
        assert "pid" not in persisted
        assert "command" not in persisted
        assert not plugin._readers
        assert not plugin._stderr_readers

    asyncio.run(exercise())


def test_resume_from_fresh_plugin_uses_persisted_spec_and_session_id(
    tmp_path, monkeypatch
):
    async def exercise():
        original_events: AsyncGenerator[RunnerEvent] | None = None
        resumed_events: AsyncGenerator[RunnerEvent] | None = None
        launch_log = tmp_path / "launch.jsonl"
        monkeypatch.setenv("FAKE_CLAUDE_LOG", str(launch_log))
        state_dir = tmp_path / "session-state"
        original = make_plugin(tmp_path, state_dir=state_dir)
        restarted = make_plugin(tmp_path, state_dir=state_dir)
        spec = SessionSpec(
            "claude-cli",
            "model-x",
            "agent-resume",
            str(tmp_path),
            "",
            "high",
            "workspace-write",
        )
        try:
            ref = await original.start(spec)
            original_events = original.events(ref)
            await next_kind(original_events, "text")
            await next_kind(original_events, "permission_requested")
            await original.close()
            resumed = await restarted.resume(SessionRef(ref.provider, ref.session_id))
            assert resumed == ref
            resumed_events = restarted.events(resumed)
            await next_kind(resumed_events, "text")
            await next_kind(resumed_events, "permission_requested")
            launches = [
                json.loads(line) for line in launch_log.read_text().splitlines()
            ]
            assert len(launches) == 2
            assert launches[0]["cwd"] == str(tmp_path)
            assert launches[1]["cwd"] == str(tmp_path)
            args = launches[1]["argv"]
            assert args[args.index("--resume") + 1] == ref.session_id
            assert args[args.index("--model") + 1] == "model-x"
            assert args[args.index("--effort") + 1] == "high"
            assert args[args.index("--permission-mode") + 1] == "acceptEdits"
        finally:
            await original.close()
            await restarted.close()
            if original_events is not None:
                await original_events.aclose()
            if resumed_events is not None:
                await resumed_events.aclose()

    asyncio.run(exercise())


def test_resume_with_new_mode_relaunches_and_persists_it(tmp_path, monkeypatch):
    async def exercise():
        launch_log = tmp_path / "launch.jsonl"
        monkeypatch.setenv("FAKE_CLAUDE_LOG", str(launch_log))
        state_dir = tmp_path / "session-state"
        original = make_plugin(tmp_path, state_dir=state_dir)
        restarted = make_plugin(tmp_path, state_dir=state_dir)
        later = make_plugin(tmp_path, state_dir=state_dir)
        spec = SessionSpec(
            "claude-cli", "m", "agent-mode", str(tmp_path), "", None, "workspace-write"
        )
        try:
            ref = await original.start(spec)
            await next_kind(original.events(ref), "text")
            await original.close()
            with pytest.raises(ValueError, match="bogus"):
                await restarted.resume(ref, ResumeSettings(mode_id="bogus"))
            await restarted.resume(ref, ResumeSettings(mode_id="read-only"))
            await next_kind(restarted.events(ref), "text")
            await restarted.close()
            await later.resume(ref)
            await next_kind(later.events(ref), "text")
            launches = [
                json.loads(line) for line in launch_log.read_text().splitlines()
            ]
            modes = [
                item["argv"][item["argv"].index("--permission-mode") + 1]
                for item in launches
            ]
            assert modes[1] == modes[2] != modes[0]
        finally:
            await original.close()
            await restarted.close()
            await later.close()

    asyncio.run(exercise())


def test_recover_orphan_waits_for_term_then_kill_and_clears_process_record(tmp_path):
    session_id = str(uuid.uuid4())
    alive = True
    signals = []

    def send_signal(process_group, value):
        nonlocal alive
        signals.append((process_group, value))
        if value == signal.SIGKILL:
            alive = False

    plugin = make_plugin(
        tmp_path,
        stop_timeout=0.04,
        process_group_exists=lambda _group: alive,
        process_group_signal=send_signal,
    )
    plugin._persist_spec(
        session_id, SessionSpec("claude-cli", "model", "agent", str(tmp_path))
    )
    state_path = plugin._spec_path(session_id)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    command = [str(FAKE), "--session-id", session_id]
    state.update(
        pid=4321,
        process_group=4321,
        command=command,
        started_at="test-start",
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    async def recover():
        return await plugin.recover_orphans()

    assert asyncio.run(recover()) == set()
    assert [value for _, value in signals] == [signal.SIGTERM, signal.SIGKILL]
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert not {"pid", "process_group", "command", "started_at"} & persisted.keys()


def test_recover_orphan_clears_state_when_inspector_finds_no_process(tmp_path):
    session_id = str(uuid.uuid4())
    plugin = make_plugin(tmp_path, process_inspector=lambda _pid, _command: None)
    plugin._persist_spec(
        session_id, SessionSpec("claude-cli", "model", "agent", str(tmp_path))
    )
    state_path = plugin._spec_path(session_id)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        pid=4321,
        process_group=4321,
        command=[str(FAKE), "--session-id", session_id],
        started_at="old-start",
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    assert asyncio.run(plugin.recover_orphans()) == set()
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert not {"pid", "process_group", "command", "started_at"} & persisted.keys()


def test_resume_without_persisted_metadata_fails_cleanly(tmp_path):
    async def exercise():
        plugin = make_plugin(tmp_path)
        with pytest.raises(RuntimeError, match="metadata is unavailable"):
            await plugin.resume(
                SessionRef("claude-cli", "e3d2a2ef-444a-4d96-9788-f82cf14e7a2b")
            )
        assert not plugin._processes

    asyncio.run(exercise())


def test_remove_spec_clears_cached_spec(tmp_path):
    plugin = make_plugin(tmp_path)
    session_id = str(uuid.uuid4())
    spec = SessionSpec("claude-cli", "model", "workspace", str(tmp_path))
    plugin._specs[session_id] = spec
    plugin._persist_spec(session_id, spec)

    plugin.remove_spec(session_id)

    assert session_id not in plugin._specs
    assert not plugin._spec_path(session_id).exists()


def test_result_events_and_provider_limit_classification(tmp_path):
    async def exercise():
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("claude-cli", "model", "agent-result", str(tmp_path))
        )
        events = plugin.events(ref)
        try:
            await next_kind(events, "text")
            await next_kind(events, "permission_requested")
            await plugin.send(ref, "complete")
            end = await next_kind(events, "session_end")
            assert end.payload["status"] == "completed"
            await next_kind(events, "status")
            usage = await next_kind(events, "usage")
            assert usage.payload["usage"] == {"input_tokens": 1}
        finally:
            await plugin.close()
            await events.aclose()
        assert plugin.is_provider_limit_error(
            RuntimeError({"error": {"type": "usage_limit_exceeded"}})
        )
        assert plugin.is_provider_limit_error(RuntimeError("Hit your usage limit"))
        assert not plugin.is_provider_limit_error(RuntimeError("ordinary failure"))

    asyncio.run(exercise())


def test_process_exit_is_classified_by_current_turn_state(tmp_path):
    async def exercise():
        plugin = make_plugin(tmp_path)
        idle_ref = await plugin.start(
            SessionSpec("claude-cli", "model", "agent-idle-kill", str(tmp_path))
        )
        idle_events = plugin.events(idle_ref)
        try:
            await next_kind(idle_events, "text")
            await next_kind(idle_events, "permission_requested")
            await plugin.send(idle_ref, "complete")
            assert (await next_kind(idle_events, "session_end")).payload[
                "status"
            ] == "completed"
            await next_kind(idle_events, "status")
            await next_kind(idle_events, "usage")
            assert await plugin.idle_status(idle_ref) == "idle"

            idle_process = plugin._processes[idle_ref.session_id]
            os.kill(idle_process.pid, signal.SIGKILL)
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(anext(idle_events), 2)
        finally:
            await plugin.close()
            await idle_events.aclose()

        active_ref = await plugin.start(
            SessionSpec("claude-cli", "model", "agent-active-kill", str(tmp_path))
        )
        active_events = plugin.events(active_ref)
        try:
            await next_kind(active_events, "text")
            await next_kind(active_events, "permission_requested")
            await plugin.send(active_ref, "complete")
            assert (await next_kind(active_events, "session_end")).payload[
                "status"
            ] == "completed"
            await next_kind(active_events, "status")
            await next_kind(active_events, "usage")
            await plugin.send(active_ref, "next turn")
            await next_kind(active_events, "text")
            active_process = plugin._processes[active_ref.session_id]
            os.kill(active_process.pid, signal.SIGKILL)
            error = await next_kind(active_events, "error")
            assert error.payload["message"] == "Claude process exited unexpectedly"
            failed = await next_kind(active_events, "session_end")
            assert failed.payload["status"] == "failed"
            assert failed.payload["terminal"] is True
        finally:
            await plugin.close()
            await active_events.aclose()

    asyncio.run(exercise())


def test_dead_process_operations_and_unexpected_midturn_exit(tmp_path, monkeypatch):
    async def exercise():
        monkeypatch.setenv("FAKE_CLAUDE_EXIT_ON_USER", "1")
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("claude-cli", "model", "agent-idle-exit", str(tmp_path))
        )
        events = plugin.events(ref)
        try:
            await next_kind(events, "text")
            await next_kind(events, "permission_requested")
            await plugin.send(ref, "exit during active turn")
            error = await next_kind(events, "error")
            assert error.payload["message"] == "Claude process exited unexpectedly"
            end = await next_kind(events, "session_end")
            assert end.payload["status"] == "failed"
            assert end.payload["terminal"] is True
            with pytest.raises(RuntimeError, match="not running"):
                await plugin.interrupt(ref)
            with pytest.raises(RuntimeError, match="not running"):
                await plugin.respond_permission(ref, "permit-1", "allow")
            with pytest.raises(RuntimeError, match="not running"):
                await plugin.send(ref, "after exit")
        finally:
            await plugin.close()
            await events.aclose()

    asyncio.run(exercise())


def test_interrupt_timeout_and_refusal(tmp_path, monkeypatch):
    async def exercise():
        monkeypatch.setenv("FAKE_CLAUDE_INTERRUPT_IGNORE", "1")
        plugin = make_plugin(tmp_path, interrupt_timeout=0.05)
        ref = await plugin.start(
            SessionSpec("claude-cli", "model", "agent-timeout", str(tmp_path))
        )
        events = plugin.events(ref)
        try:
            await next_kind(events, "text")
            await next_kind(events, "permission_requested")
            await plugin.send(ref, "hello")
            await next_kind(events, "text")
            with pytest.raises(TimeoutError, match="Claude interrupt timed out"):
                await plugin.interrupt(ref)
        finally:
            await plugin.close()
            await events.aclose()

        monkeypatch.delenv("FAKE_CLAUDE_INTERRUPT_IGNORE")
        monkeypatch.setenv("FAKE_CLAUDE_INTERRUPT_REFUSE", "1")
        rejected = make_plugin(tmp_path / "refusal")
        refused_ref = await rejected.start(
            SessionSpec("claude-cli", "model", "agent-refused", str(tmp_path))
        )
        refused_events = rejected.events(refused_ref)
        try:
            await next_kind(refused_events, "text")
            await next_kind(refused_events, "permission_requested")
            await rejected.send(refused_ref, "hello")
            await next_kind(refused_events, "text")
            with pytest.raises(RuntimeError, match="rejected interrupt"):
                await rejected.interrupt(refused_ref)
        finally:
            await rejected.close()
            await refused_events.aclose()

    asyncio.run(exercise())


def test_stop_kills_process_group_and_term_ignoring_process_escalates(
    tmp_path, monkeypatch
):
    async def exercise():
        child_pid_path = tmp_path / "child.pid"
        monkeypatch.setenv("FAKE_CLAUDE_CHILD_PID", str(child_pid_path))
        plugin = make_plugin(tmp_path, stop_timeout=0.1)
        ref = await plugin.start(
            SessionSpec("claude-cli", "model", "agent-kill-group", str(tmp_path))
        )
        events = plugin.events(ref)
        try:
            await next_kind(events, "text")
            await next_kind(events, "permission_requested")
            child_pid = int(child_pid_path.read_text())
            process = plugin._processes[ref.session_id]
            await plugin.stop(ref)
            assert not plugin._readers and not plugin._stderr_readers
            with pytest.raises(RuntimeError, match="not running"):
                await plugin.send(ref, "stopped")
            assert _process_stopped(child_pid)
            assert _process_group_stopped(process.pid)
        finally:
            await plugin.close()
            await events.aclose()

        monkeypatch.delenv("FAKE_CLAUDE_CHILD_PID")
        monkeypatch.setenv("FAKE_CLAUDE_IGNORE_TERM", "1")
        escalation = make_plugin(tmp_path / "escalation", stop_timeout=0.05)
        escalation_ref = await escalation.start(
            SessionSpec("claude-cli", "model", "agent-escalation", str(tmp_path))
        )
        child_events = escalation.events(escalation_ref)
        process = escalation._processes[escalation_ref.session_id]
        try:
            await next_kind(child_events, "text")
            await next_kind(child_events, "permission_requested")
            await escalation.stop(escalation_ref)
            assert process.returncode == -signal.SIGKILL
        finally:
            await escalation.close()
            await child_events.aclose()

    asyncio.run(exercise())


def test_capabilities_missing_executable_and_start_spawn_cleanup(tmp_path):
    async def exercise():
        plugin = make_plugin(tmp_path)
        assert plugin.capabilities.resume
        assert plugin.capabilities.permission_commands
        assert plugin.capabilities.usage
        assert plugin.capabilities.idle_status
        assert plugin.capabilities.persistent_process
        assert plugin.capabilities.interrupt
        assert not plugin.capabilities.steer
        assert plugin.capabilities.respond
        assert not plugin.capabilities.external_wake

        missing = ClaudeCliPlugin(
            tmp_path / "missing-claude", state_dir=tmp_path / "missing-state"
        )
        spec = SessionSpec("claude-cli", "model", "agent-missing", str(tmp_path))
        with pytest.raises(RuntimeError, match="could not be started"):
            await missing.start(spec)
        assert list((tmp_path / "missing-state").glob("*.json")) == []

        not_found = ClaudeCliPlugin(
            state_dir=tmp_path / "not-found-state", executable=None
        )
        not_found.executable = None
        with pytest.raises(RuntimeError, match="not found on PATH"):
            await not_found.start(spec)

    asyncio.run(exercise())


def _process_stopped(pid: int) -> bool:
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        time.sleep(0.02)
    return False


def _process_group_stopped(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _silent_claude(tmp_path):
    script = tmp_path / "silent-claude"
    script.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(60)\n")
    script.chmod(0o755)
    return script


def test_silent_child_does_not_emit_plugin_specific_watchdog(tmp_path):
    async def exercise():
        plugin = make_plugin(tmp_path)
        plugin.executable = str(_silent_claude(tmp_path))
        spec = SessionSpec(
            "claude-cli", "model", "workspace-1", str(tmp_path), prompt="hello"
        )
        ref = await plugin.start(spec)
        try:
            with pytest.raises(TimeoutError):
                await next_kind(plugin.events(ref), "error", timeout=1)
        finally:
            await plugin.stop(ref)

    asyncio.run(exercise())


def test_child_that_emits_frames_is_not_reported_silent(tmp_path):
    async def exercise():
        plugin = make_plugin(tmp_path)
        spec = SessionSpec(
            "claude-cli", "model", "workspace-1", str(tmp_path), prompt="hello"
        )
        ref = await plugin.start(spec)
        try:
            events = plugin.events(ref)
            await next_kind(events, "text")
            await asyncio.sleep(0.6)
            while not plugin._queues[ref.session_id].empty():
                event = plugin._queues[ref.session_id].get_nowait()
                assert event is None or "silent" not in str(event.payload)
        finally:
            await plugin.stop(ref)

    asyncio.run(exercise())
