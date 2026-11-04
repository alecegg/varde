import asyncio
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import varde_runner.plugins.codex_app_server.plugin as plugin_module
from varde_runner.plugins import SessionRef, SessionSpec
from varde_runner.plugins.codex_app_server.plugin import (
    CodexAppServerPlugin,
    ProcessIdentity,
    _Session,
)

FAKE = Path(__file__).parent / "fakes" / "fake_codex_app_server.py"


def make_plugin(tmp_path, **kwargs):
    executable = kwargs.pop("executable", FAKE)
    kwargs.setdefault("state_dir", tmp_path / "state")
    kwargs.setdefault(
        "process_inspector",
        lambda _pid, command: ProcessIdentity("test", " ".join(command)),
    )
    return CodexAppServerPlugin(executable, **kwargs)


def test_process_alive_tracks_returncode(tmp_path):
    plugin = make_plugin(tmp_path)
    ref = SessionRef("codex-app-server", "session-1")
    process = SimpleNamespace(returncode=None)
    plugin._sessions[ref.session_id] = _Session(
        process=cast("asyncio.subprocess.Process", process)
    )
    assert plugin.process_alive(ref)
    process.returncode = 0
    assert not plugin.process_alive(ref)


async def next_kind(events, kind):
    async def find():
        async for event in events:
            if event.kind == kind:
                return event
        raise AssertionError(f"missing event {kind}")

    return await asyncio.wait_for(find(), 3)


def test_process_lifecycle_steer_permissions_usage_resume_and_orphans(
    tmp_path, monkeypatch
):
    async def run():
        monkeypatch.setenv("FAKE_CODEX_LOG", str(tmp_path / "codex.log"))
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        events = plugin.events(ref)
        try:
            await plugin.send(ref, "approval")
            permission = await next_kind(events, "permission_requested")
            assert permission.payload["rpc_id"] == 42
            assert permission.payload["kind"] == "tool"
            assert permission.payload["tool"] == "commandExecution"
            assert permission.payload["item_id"] == "item-1"
            assert permission.payload["thread_id"] == "thread-fake"
            assert permission.payload["turn_id"] == "turn-fake"
            await plugin.respond_permission(
                ref, permission.payload["request_id"], "allow"
            )
            await plugin.respond_permission(
                ref, permission.payload["request_id"], "allow"
            )
            await next_kind(events, "permission_resolved")
            await plugin.respond_permission(
                ref, permission.payload["request_id"], "allow"
            )
            await next_kind(events, "error")
            await next_kind(events, "session_end")
            await plugin.send(ref, "limit")
            usage = await next_kind(events, "usage")
            assert usage.payload["limit"]["primary"]["used_percent"] == 90
            await next_kind(events, "session_end")
            await plugin.send(ref, "hello")
            await plugin.send(ref, "follow-up")
            await next_kind(events, "session_end")
            await plugin.close()
            fresh = make_plugin(tmp_path, state_dir=plugin.state_dir)
            resumed = await fresh.resume(SessionRef(ref.provider, ref.session_id))
            assert resumed == ref
            await fresh.stop(resumed)
            await fresh.close()
        finally:
            await plugin.close()

    asyncio.run(run())


def test_failed_interrupt_does_not_submit_a_new_prompt(tmp_path, monkeypatch):
    async def run():
        log = tmp_path / "codex.log"
        monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
        monkeypatch.setenv("FAKE_CODEX_IGNORE_INTERRUPT", "1")
        plugin = make_plugin(tmp_path, interrupt_timeout=0.02)
        ref = await plugin.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        try:
            await plugin.send(ref, "hold")
            with pytest.raises(TimeoutError, match="failed_interrupt"):
                await plugin.interrupt(ref)
            methods = [
                json.loads(line).get("method") for line in log.read_text().splitlines()
            ]
            assert methods[-1] == "turn/interrupt"
            assert "turn/start" not in methods[methods.index("turn/interrupt") + 1 :]
        finally:
            await plugin.close()

    asyncio.run(run())


def test_successful_interrupt_waits_for_turn_completed(tmp_path, monkeypatch):
    async def run():
        log = tmp_path / "codex.log"
        monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        events = plugin.events(ref)
        try:
            await plugin.send(ref, "hold")
            await plugin.interrupt(ref)
            event = await next_kind(events, "session_end")
            assert event.payload["status"] == "interrupted"
            methods = [
                json.loads(line).get("method") for line in log.read_text().splitlines()
            ]
            assert methods.count("turn/interrupt") == 1
        finally:
            await plugin.close()

    asyncio.run(run())


def test_turn_status_effort_and_terminal_observation(tmp_path, monkeypatch, caplog):
    caplog.set_level("INFO")

    async def run():
        log = tmp_path / "codex.log"
        monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
        monkeypatch.setenv("FAKE_CODEX_COMPLETION_STATUS", "failed")
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec(
                "codex-app-server",
                "gpt-test",
                "agent",
                str(tmp_path),
                reasoning_effort="low",
            )
        )
        events = plugin.events(ref)
        try:
            await plugin.send(ref, "hello")
            request = next(
                json.loads(line)
                for line in log.read_text().splitlines()
                if json.loads(line).get("method") == "turn/start"
            )
            assert request["params"]["effort"] == "low"
            assert (await next_kind(events, "status")).payload["status"] == "running"
            terminal = await next_kind(events, "session_end")
            assert terminal.payload["status"] == "failed"
            assert (await next_kind(events, "status")).payload["status"] == "error"
            assert await plugin.idle_status(ref) == "error"
            assert "codex_turn_observation" in caplog.text
            assert "terminal_status=failed" in caplog.text
        finally:
            await plugin.close()

    asyncio.run(run())


def test_protocol_errors_are_logged_and_published(tmp_path, monkeypatch, caplog):
    async def run():
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        events = plugin.events(ref)
        try:
            await plugin.send(ref, "malformed")
            malformed = await next_kind(events, "error")
            assert malformed.payload["count"] == 1
            assert len(malformed.payload["prefix"]) <= 82
            assert "codex_stdout_non_json" in caplog.text
            await next_kind(events, "session_end")
            await next_kind(events, "status")
            await plugin.send(ref, "notify-error")
            retry = await next_kind(events, "status")
            while "will_retry" not in retry.payload:
                retry = await next_kind(events, "status")
            assert retry.payload["will_retry"] is True
            assert retry.payload["thread_id"] == "thread-fake"
            assert retry.payload["turn_id"] == "turn-fake"
            assert "codex_error" in caplog.text
        finally:
            await plugin.close()

    asyncio.run(run())


def test_turn_started_timeout_is_published(tmp_path, monkeypatch, caplog):
    async def run():
        monkeypatch.setenv("FAKE_CODEX_NO_TURN_STARTED", "1")
        plugin = make_plugin(tmp_path)
        plugin._TURN_STARTED_TIMEOUT = 0.01
        ref = await plugin.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        events = plugin.events(ref)
        try:
            with pytest.raises(TimeoutError, match="turn/started"):
                await plugin.send(ref, "hello")
            failure = await next_kind(events, "error")
            assert "timed out" in failure.payload["message"]
            assert "turn_start_wait_timeout" in caplog.text
        finally:
            await plugin.close()

    asyncio.run(run())


def test_probe_rejects_old_and_missing_schema(tmp_path, monkeypatch):
    async def run():
        plugin = make_plugin(tmp_path)
        CodexAppServerPlugin._probe_cache.clear()
        monkeypatch.setenv("FAKE_CODEX_OLD", "1")
        with pytest.raises(RuntimeError, match="version"):
            await plugin.start(SessionSpec("codex-app-server", "m", "a", str(tmp_path)))
        monkeypatch.delenv("FAKE_CODEX_OLD")
        CodexAppServerPlugin._probe_cache.clear()
        monkeypatch.setenv("FAKE_CODEX_MISSING_METHOD", "1")
        with pytest.raises(RuntimeError, match="turn/steer"):
            await plugin.start(SessionSpec("codex-app-server", "m", "a", str(tmp_path)))
        monkeypatch.delenv("FAKE_CODEX_MISSING_METHOD")
        CodexAppServerPlugin._probe_cache.clear()

    asyncio.run(run())


def test_schema_probe_matches_exact_method_names(tmp_path):
    from varde_runner.plugins.codex_app_server import wire

    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"description": "turn/steerExtra"}))
    assert CodexAppServerPlugin._schema_methods(schema) == set()
    schema.write_text(json.dumps({"method": "turn/steer"}))
    assert CodexAppServerPlugin._schema_methods(schema) == {"turn/steer"}
    assert "turn/steer" in wire.REQUIRED_METHODS


def test_probe_cache_invalidates_when_executable_mtime_changes(tmp_path, monkeypatch):
    async def run():
        executable = tmp_path / "codex"
        executable.write_text("codex")
        plugin = make_plugin(tmp_path, executable=executable)
        calls = 0

        async def probe(_binary):
            nonlocal calls
            calls += 1
            return ()

        monkeypatch.setattr(plugin, "_probe_binary", probe)
        await plugin._probe()
        plugin._probed = False
        await plugin._probe()
        assert calls == 1
        stat = executable.stat()
        executable.touch()
        executable.chmod(0o755)
        os.utime(executable, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        plugin._probed = False
        await plugin._probe()
        assert calls == 2

    asyncio.run(run())


def test_send_preserves_rpc_error_after_session_is_removed(tmp_path, monkeypatch):
    async def run():
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        process = plugin._sessions[ref.session_id].process
        original = RuntimeError("original RPC failure")

        async def remove_then_fail(_ref, _raw, _method):
            plugin._clear_live_state(ref.session_id)
            raise original

        monkeypatch.setattr(plugin, "_rpc", remove_then_fail)
        try:
            with pytest.raises(RuntimeError, match="original RPC failure") as caught:
                await plugin.send(ref, "hello")
            assert caught.value is original
        finally:
            if process is not None and process.returncode is None:
                process.terminate()
                await process.wait()
            await plugin.close()

    asyncio.run(run())


def test_failed_spec_load_does_not_create_session(tmp_path):
    plugin = make_plugin(tmp_path)
    ref = SessionRef("codex-app-server", "00000000-0000-4000-8000-000000000000")

    with pytest.raises(RuntimeError, match="cannot restore Codex session"):
        plugin._load_spec(ref)

    assert ref.session_id not in plugin._sessions


def test_probe_against_installed_codex(tmp_path):
    executable = shutil.which("codex")
    if executable is None:
        pytest.skip("codex is not installed on PATH")

    async def run():
        plugin = make_plugin(tmp_path, executable=executable)
        await plugin._probe()

    asyncio.run(run())


def test_server_request_id_can_match_client_request_id(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setenv("FAKE_CODEX_COLLISION", "1")
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        events = plugin.events(ref)
        try:
            request = await next_kind(events, "permission_requested")
            assert request.payload["rpc_id"] == "varde-2"
            await plugin.respond_permission(ref, request.payload["request_id"], "deny")
        finally:
            await plugin.close()

    asyncio.run(run())


def test_concurrent_send_waits_for_turn_started_then_steers(tmp_path, monkeypatch):
    async def run():
        log = tmp_path / "codex.log"
        monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
        monkeypatch.setenv("FAKE_CODEX_DELAY_START", "1")
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        try:
            first = asyncio.create_task(plugin.send(ref, "first"))
            await asyncio.sleep(0.01)
            second = asyncio.create_task(plugin.send(ref, "second"))
            await asyncio.gather(first, second)
            requests = [json.loads(line) for line in log.read_text().splitlines()]
            methods = [request.get("method") for request in requests]
            assert "turn/start" in methods and "turn/steer" in methods
            steer = next(
                request for request in requests if request.get("method") == "turn/steer"
            )
            assert steer["params"]["expectedTurnId"] == "turn-fake"
            assert steer["params"]["input"][0]["text"] == "second"
        finally:
            await plugin.close()

    asyncio.run(run())


def test_steer_rpc_error_resets_turn_state(tmp_path):
    async def run():
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        try:
            await plugin.send(ref, "hold")
            with pytest.raises(RuntimeError, match="turn rejected"):
                await plugin.send(ref, "reject-steer")
            assert await plugin.idle_status(ref) == "idle"
            assert plugin._sessions[ref.session_id].turn_id is None
        finally:
            await plugin.close()

    asyncio.run(run())


def test_turn_start_rpc_error_resets_state_and_waiters(tmp_path):
    async def run():
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        events = plugin.events(ref)
        try:
            with pytest.raises(RuntimeError, match="turn rejected"):
                await plugin.send(ref, "reject")
            failure = await next_kind(events, "error")
            assert "turn rejected" in failure.payload["message"]
            assert await plugin.idle_status(ref) == "idle"
            assert not plugin._rpc_waiters and not plugin._rpc_methods
        finally:
            await plugin.close()

    asyncio.run(run())


def test_question_response_fails_closed_and_unknown_ids_surface(tmp_path, monkeypatch):
    async def run():
        log = tmp_path / "codex.log"
        monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        events = plugin.events(ref)
        try:
            await plugin.send(ref, "question")
            request = await next_kind(events, "wait_created")
            await plugin.respond_permission(ref, request.payload["request_id"], "allow")
            error = await next_kind(events, "error")
            assert "unsupported" in error.payload["message"]
            assert (await next_kind(events, "text")).payload[
                "text"
            ] == "question-denied"
            await plugin.respond_permission(ref, "unknown", "allow")
            stale = await next_kind(events, "error")
            assert "unknown" in stale.payload["message"]
            assert '"id": "question-1"' in log.read_text()
            assert '"error"' in log.read_text()
        finally:
            await plugin.close()

    asyncio.run(run())


def test_crash_is_classified_and_large_line_terminates_process(tmp_path, monkeypatch):
    async def run():
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        events = plugin.events(ref)
        try:
            with pytest.raises(RuntimeError, match="process exited"):
                await plugin.send(ref, "crash")
            failure = await next_kind(events, "session_end")
            assert failure.payload["status"] == "failed"
            assert failure.payload["terminal"] is True
        finally:
            await plugin.close()

        monkeypatch.setattr(plugin_module, "MAX_STDOUT_LINE_BYTES", 1024)
        monkeypatch.setenv("FAKE_CODEX_LARGE_BYTES", "2048")
        second = make_plugin(tmp_path, state_dir=tmp_path / "large-state")
        ref2 = await second.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        events2 = second.events(ref2)
        try:
            with pytest.raises(RuntimeError, match="process exited"):
                await second.send(ref2, "large")
            error = await next_kind(events2, "error")
            assert "configured limit" in error.payload["message"]
        finally:
            await second.close()

    asyncio.run(run())


@pytest.mark.parametrize("method", ["initialize", "thread/start"])
def test_non_turn_rpc_failure_is_raised_without_error_event(
    tmp_path, monkeypatch, method
):
    async def run():
        monkeypatch.setenv("FAKE_CODEX_RPC_FAIL", method)
        plugin = make_plugin(tmp_path)
        try:
            emitted = []
            original_event = plugin_module._event

            def capture_event(kind, *args, **kwargs):
                emitted.append(kind)
                return original_event(kind, *args, **kwargs)

            monkeypatch.setattr(plugin_module, "_event", capture_event)
            with pytest.raises(RuntimeError, match="failed"):
                await plugin.start(
                    SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
                )
            assert "error" not in emitted
        finally:
            await plugin.close()

    asyncio.run(run())


def test_resume_keeps_existing_event_stream_open(tmp_path):
    async def run():
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        events = plugin.events(ref)
        try:
            await plugin.send(ref, "initial")
            await next_kind(events, "session_end")
            await plugin.resume(ref)
            await plugin.send(ref, "after-resume")
            resumed_end = await next_kind(events, "session_end")
            assert resumed_end.payload["status"] == "completed"
        finally:
            await plugin.close()
            await events.aclose()

    asyncio.run(run())


def test_failed_resume_cleans_child_and_reports_to_existing_event_stream(
    tmp_path, monkeypatch
):
    async def run():
        plugin = make_plugin(tmp_path)
        ref = await plugin.start(
            SessionSpec("codex-app-server", "gpt-test", "agent", str(tmp_path))
        )
        events = plugin.events(ref)
        monkeypatch.setenv("FAKE_CODEX_RESUME_FAIL", "1")
        try:
            await plugin.send(ref, "initial")
            await next_kind(events, "session_end")
            await next_kind(events, "status")
            waiter = asyncio.create_task(anext(events))
            with pytest.raises(RuntimeError, match="resume failed"):
                await plugin.resume(ref)
            event = await asyncio.wait_for(waiter, 3)
            assert "resume failed" in event.payload["message"]
            session = plugin._sessions.get(ref.session_id)
            assert session is None or session.process is None
        finally:
            await plugin.close()
            await events.aclose()

    asyncio.run(run())


def test_orphan_sweep_clears_gone_process_identity(tmp_path):
    async def run():
        plugin = make_plugin(tmp_path, process_inspector=lambda _pid, _command: None)
        session_id = "024f4550-cf88-4a13-bdd7-ae4ff439c657"
        spec = SessionSpec("codex-app-server", "m", "agent", str(tmp_path))
        plugin._persist_spec(session_id, spec)
        value = json.loads(plugin._spec_path(session_id).read_text())
        value.update(
            pid=999999,
            process_group=999999,
            command=["codex", "app-server"],
            started_at="old",
        )
        plugin._write_state(plugin._spec_path(session_id), value)
        assert await plugin.recover_orphans() == set()
        persisted = json.loads(plugin._spec_path(session_id).read_text())
        assert "pid" not in persisted and "process_group" not in persisted

    asyncio.run(run())


def test_remove_spec_clears_cached_spec(tmp_path):
    plugin = make_plugin(tmp_path)
    session_id = "024f4550-cf88-4a13-b13d-7ae4cf080321"
    spec = SessionSpec("codex-app-server", "model", "workspace", str(tmp_path))
    plugin._sessions[session_id] = _Session(spec=spec)
    plugin._persist_spec(session_id, spec)

    plugin.remove_spec(session_id)

    assert plugin._sessions[session_id].spec is None
    assert not plugin._spec_path(session_id).exists()
