import asyncio
from types import SimpleNamespace

import pytest
from varde_runner.diagnostic import (
    StartupTimeout,
    append_startup_diagnostic,
    startup_diagnostic,
    startup_timeout_error,
)
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSpec
from varde_runner.protocol import plugin_is_provider_limit_error
from varde_runner.supervisor import SendOutcome, Supervisor


def test_diagnostic_is_actionable_and_names_both_executables():
    spec = SessionSpec("provider", "model", "workspace", "/work")
    message = startup_diagnostic(spec, "darwin", 31.2, "/bin/runner", "/bin/python")
    assert "produced no output" in message
    assert "Files and Folders" in message
    assert "/bin/runner" in message
    assert "/bin/python" in message
    assert "/work" in message
    assert "clean probe" not in message


class SilentPlugin:
    capabilities = RunnerCapabilities(
        resume=True, idle_status=True, persistent_process=True
    )

    def __init__(self, error=None):
        self.error = error
        self.resume_error: BaseException | None = None
        self.spec = None
        self.queue = asyncio.Queue()
        self.sends = 0
        self.send_error: BaseException | None = None

    async def start(self, spec):
        self.spec = spec
        if self.error:
            raise self.error
        return SessionRef("provider", "remote")

    async def resume(self, ref):
        if self.resume_error:
            raise self.resume_error
        return ref

    def _load_spec(self, ref):
        return self.spec

    def is_provider_limit_error(self, error):
        details = error.args[0] if error.args else {}
        nested = details.get("error", details) if isinstance(details, dict) else {}
        return nested.get("type") == "usage_limit_exceeded"

    async def send(self, ref, prompt):
        self.sends += 1
        if self.send_error:
            raise self.send_error

    async def idle_status(self, ref):
        return "idle"

    async def events(self, ref):
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event

    async def stop(self, ref):
        pass

    async def close(self):
        pass


def _short_timeout(monkeypatch, timeout=0.02):
    monkeypatch.setattr(
        "varde_runner.supervisor.load_config",
        lambda *_: SimpleNamespace(startup_timeout_s=timeout),
    )


def test_prompt_start_warns_once_then_recovers(tmp_path, monkeypatch):
    _short_timeout(monkeypatch)

    async def run():
        plugin = SilentPlugin()
        supervisor = Supervisor(tmp_path, {"provider": plugin})
        session = await supervisor.start_session(
            SessionSpec(
                "provider", "model", "workspace", str(tmp_path), prompt="hello"
            ),
            "builder",
        )
        await asyncio.sleep(0.05)
        warnings = [
            event
            for event in supervisor.store.latest_events(session.session_id, 50)
            if event["kind"] == "warning"
        ]
        assert len(warnings) == 1
        await supervisor.send(session.session_id, "later")
        await asyncio.sleep(0.04)
        warnings = [
            event
            for event in supervisor.store.latest_events(session.session_id, 50)
            if event["kind"] == "warning"
        ]
        assert len(warnings) == 1
        await supervisor.record_event(session.session_id, "text", {"text": "ready"})
        assert any(
            event["kind"] == "activity"
            and event["payload"].get("message") == "startup recovered"
            for event in supervisor.store.latest_events(session.session_id, 50)
        )
        await supervisor.shutdown()

    asyncio.run(run())


def test_first_send_arms_once_and_promptless_start_does_not(tmp_path, monkeypatch):
    _short_timeout(monkeypatch)

    async def run():
        supervisor = Supervisor(tmp_path, {"provider": SilentPlugin()})
        session = await supervisor.start_session(
            SessionSpec("provider", "model", "workspace", str(tmp_path)), "builder"
        )
        await asyncio.sleep(0.04)
        assert not any(
            event["kind"] == "warning"
            for event in supervisor.store.latest_events(session.session_id, 50)
        )
        assert await supervisor.send(session.session_id, "first") == SendOutcome.SENT
        await asyncio.sleep(0.04)
        assert (
            len(
                [
                    e
                    for e in supervisor.store.latest_events(session.session_id, 50)
                    if e["kind"] == "warning"
                ]
            )
            == 1
        )
        await supervisor.send(session.session_id, "second")
        await asyncio.sleep(0.04)
        assert (
            len(
                [
                    e
                    for e in supervisor.store.latest_events(session.session_id, 50)
                    if e["kind"] == "warning"
                ]
            )
            == 1
        )
        await supervisor.shutdown()

    asyncio.run(run())


def test_early_event_keeps_first_send_diagnostic_eligible(tmp_path, monkeypatch):
    _short_timeout(monkeypatch)

    async def run():
        plugin = SilentPlugin()
        supervisor = Supervisor(tmp_path, {"provider": plugin})
        session = await supervisor.start_session(
            SessionSpec("provider", "model", "workspace", str(tmp_path)), "builder"
        )
        await supervisor.record_event(session.session_id, "system", {})
        assert await supervisor.send(session.session_id, "first") == SendOutcome.SENT
        await asyncio.sleep(0.04)
        assert any(
            event["kind"] == "warning"
            for event in supervisor.store.latest_events(session.session_id, 50)
        )
        await supervisor.shutdown()

    asyncio.run(run())


def test_failed_first_send_cancels_diagnostic(tmp_path, monkeypatch):
    _short_timeout(monkeypatch, 0.03)

    async def run():
        plugin = SilentPlugin()
        plugin.send_error = RuntimeError("child is unavailable")
        supervisor = Supervisor(tmp_path, {"provider": plugin})
        session = await supervisor.start_session(
            SessionSpec("provider", "model", "workspace", str(tmp_path)), "builder"
        )
        assert await supervisor.send(session.session_id, "first") == SendOutcome.FAILED
        await asyncio.sleep(0.05)
        assert not any(
            event["kind"] == "warning"
            for event in supervisor.store.latest_events(session.session_id, 50)
        )
        await supervisor.shutdown()

    asyncio.run(run())


def test_startup_timeout_config_is_read_once_per_supervisor(tmp_path, monkeypatch):
    reads = 0

    def load_config(*_args):
        nonlocal reads
        reads += 1
        return SimpleNamespace(startup_timeout_s=0.02)

    monkeypatch.setattr("varde_runner.supervisor.load_config", load_config)

    async def run():
        supervisor = Supervisor(tmp_path, {"provider": SilentPlugin()})
        session = await supervisor.start_session(
            SessionSpec("provider", "model", "workspace", str(tmp_path)), "builder"
        )
        await supervisor.send(session.session_id, "first")
        await asyncio.sleep(0.04)
        assert reads == 1
        await supervisor.shutdown()

    asyncio.run(run())


def test_child_exit_before_deadline_cancels_warning(tmp_path, monkeypatch):
    _short_timeout(monkeypatch, 0.05)

    async def run():
        plugin = SilentPlugin()
        supervisor = Supervisor(tmp_path, {"provider": plugin})
        session = await supervisor.start_session(
            SessionSpec(
                "provider", "model", "workspace", str(tmp_path), prompt="hello"
            ),
            "builder",
        )
        await plugin.queue.put(None)
        await asyncio.sleep(0.08)
        assert not any(
            event["kind"] == "warning"
            for event in supervisor.store.latest_events(session.session_id, 50)
        )
        await supervisor.shutdown()

    asyncio.run(run())


def test_start_timeout_preserves_error_and_dict_args(tmp_path):
    error = TimeoutError(
        {"error": {"type": "usage_limit_exceeded", "message": "limited"}}
    )

    async def run():
        plugin = SilentPlugin(error)
        supervisor = Supervisor(tmp_path, {"provider": plugin})
        with pytest.raises(TimeoutError) as caught:
            await supervisor.start_session(
                SessionSpec(
                    "provider", "model", "workspace", str(tmp_path), prompt="hello"
                ),
                "builder",
            )
        assert caught.value.args[0]["error"]["type"] == "usage_limit_exceeded"
        assert "produced no output" in caught.value.args[0]["error"]["message"]
        assert plugin_is_provider_limit_error(plugin, caught.value)
        await supervisor.shutdown()

    asyncio.run(run())


def test_resume_timeout_diagnostic_uses_persisted_cwd(tmp_path):
    async def run():
        plugin = SilentPlugin()
        supervisor = Supervisor(tmp_path, {"provider": plugin})
        session = await supervisor.start_session(
            SessionSpec("provider", "model", "workspace", "/persisted/workspace"),
            "builder",
        )
        supervisor._refs.pop(session.session_id)
        plugin.resume_error = TimeoutError("resume handshake timed out")
        assert await supervisor._target_for_send(session.session_id, None) is None
        error = next(
            event
            for event in supervisor.store.latest_events(session.session_id, 50)
            if event["kind"] == "error"
        )
        assert "/persisted/workspace" in error["payload"]["message"]
        assert "produced no output" in error["payload"]["message"]
        await supervisor.shutdown()

    asyncio.run(run())


def test_non_timeout_start_failure_gets_no_diagnostic(tmp_path):
    error = ValueError("bad model")

    async def run():
        supervisor = Supervisor(tmp_path, {"provider": SilentPlugin(error)})
        with pytest.raises(ValueError) as caught:
            await supervisor.start_session(
                SessionSpec(
                    "provider", "model", "workspace", str(tmp_path), prompt="hello"
                ),
                "builder",
            )
        assert caught.value.args == ("bad model",)
        assert "produced no output" not in str(caught.value)
        await supervisor.shutdown()

    asyncio.run(run())


def test_startup_timeout_classifier_rejects_unrelated_timeout_messages():
    assert startup_timeout_error(TimeoutError("startup handshake expired"))
    assert startup_timeout_error(StartupTimeout("probe timed out"))
    assert not startup_timeout_error(RuntimeError("provider request timed out"))
    assert not startup_timeout_error(ValueError("bad model"))


def test_append_diagnostic_updates_oserror_strerror_without_changing_args():
    error = OSError(13, "permission denied", "/workspace")
    original_args = error.args
    append_startup_diagnostic(
        error,
        SessionSpec("provider", "model", "workspace", "/workspace"),
        31,
        "/bin/runner",
        "/bin/python",
    )
    assert error.args == original_args
    assert "produced no output" in str(error)
