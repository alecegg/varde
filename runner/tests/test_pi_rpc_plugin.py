from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from varde_runner.plugins import SessionSpec
from varde_runner.plugins.pi_rpc.plugin import PiRpcPlugin

FAKE = Path(__file__).parent / "fakes" / "fake_pi_rpc.py"


def _spec(cwd: Path) -> SessionSpec:
    return SessionSpec(
        "pi-rpc",
        "model",
        "agent",
        str(cwd),
        mode_id="read-only",
        agent_id="runner-agent-id",
        runner_harness="pi",
    )


def _read_log(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_large_frame_is_read_without_truncation(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setenv("FAKE_PI_LARGE_FRAME", "1")
        plugin = PiRpcPlugin(FAKE, state_dir=tmp_path / "state")
        ref = await plugin.start(_spec(tmp_path))
        try:
            events = plugin.events(ref)
            large_error = await asyncio.wait_for(anext(events), 2)
            assert large_error.kind == "error"
            assert len(large_error.payload["message"]) > 64 * 1024
            await events.aclose()
        finally:
            await plugin.close()

    asyncio.run(run())


def test_prompt_steer_abort_stats_and_resume(tmp_path, monkeypatch):
    async def run():
        log_path = tmp_path / "commands.jsonl"
        monkeypatch.setenv("FAKE_PI_LOG", str(log_path))
        monkeypatch.setenv("FAKE_PI_HOLD_PROMPT", "1")
        plugin = PiRpcPlugin(FAKE, state_dir=tmp_path / "state")
        ref = await plugin.start(_spec(tmp_path))
        try:
            assert await plugin.idle_status(ref) == "idle"
            assert await plugin.usage(ref) == {
                "source": "pi",
                "input_tokens": 8,
                "output_tokens": 3,
                "cache_read_tokens": None,
                "cache_write_tokens": None,
                "total_tokens": 11,
                "cost": 0.02,
            }
            prompt_task = asyncio.create_task(plugin.send(ref, "long prompt"))
            for _ in range(100):
                if await plugin.idle_status(ref) == "running":
                    break
                await asyncio.sleep(0.01)
            assert await plugin.idle_status(ref) == "running"
            await plugin.send(ref, "steer while running")
            await plugin.interrupt(ref)
            await asyncio.wait_for(prompt_task, 2)

            events = plugin.events(ref)
            statuses = []
            while True:
                event = await asyncio.wait_for(anext(events), 2)
                if event.kind == "status":
                    statuses.append(event.payload)
                    if event.payload.get("aborted") is True:
                        break
            assert any(event.get("status") == "running" for event in statuses)
            assert statuses[-1] == {"status": "idle", "aborted": True}
            await events.aclose()

            commands = _read_log(log_path)
            assert [item.get("type") for item in commands] == [
                "get_session_stats",
                "get_session_stats",
                "prompt",
                "steer",
                "abort",
            ]
            await plugin.stop(ref)
            assert await plugin.resume(ref) == ref
            assert plugin._specs[ref.session_id].agent_id == "runner-agent-id"
            assert plugin._specs[ref.session_id].runner_harness == "pi"
        finally:
            await plugin.close()

    asyncio.run(run())


def test_dialog_request_is_cancelled_over_rpc_stdin(tmp_path, monkeypatch):
    async def run():
        log_path = tmp_path / "commands.jsonl"
        monkeypatch.setenv("FAKE_PI_LOG", str(log_path))
        monkeypatch.setenv("FAKE_PI_DIALOG", "1")
        plugin = PiRpcPlugin(FAKE, state_dir=tmp_path / "state")
        ref = await plugin.start(_spec(tmp_path))
        try:
            await plugin.send(ref, "prompt with a dialog")
            records = _read_log(log_path)
            dialog_response = next(
                record
                for record in records
                if record.get("type") == "extension_ui_response"
            )
            assert dialog_response == {
                "type": "extension_ui_response",
                "id": "dialog-1",
                "cancelled": True,
            }
        finally:
            await plugin.close()

    asyncio.run(run())


def test_missing_stats_falls_back_to_unknown(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setenv("FAKE_PI_MISSING_STATS", "1")
        plugin = PiRpcPlugin(FAKE, state_dir=tmp_path / "state")
        ref = await plugin.start(_spec(tmp_path))
        try:
            assert await plugin.usage(ref) == {"source": "pi", "usage": "unknown"}
        finally:
            await plugin.close()

    asyncio.run(run())


def test_process_exit_during_prompt_raises_instead_of_completing(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setenv("FAKE_PI_CRASH_PROMPT", "1")
        plugin = PiRpcPlugin(FAKE, state_dir=tmp_path / "state")
        ref = await plugin.start(_spec(tmp_path))
        process = plugin._processes[ref.session_id]
        try:
            try:
                await plugin.send(ref, "crash during prompt")
            except RuntimeError as exc:
                assert "Pi RPC process is not running" in str(exc)
            await asyncio.wait_for(process.wait(), 1)
        finally:
            await plugin.close()

    asyncio.run(run())


def test_provider_auth_failure_is_visible_and_finishes_turn(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setenv("FAKE_PI_AUTH_ERROR", "1")
        plugin = PiRpcPlugin(FAKE, state_dir=tmp_path / "state")
        ref = await plugin.start(_spec(tmp_path))
        try:
            await asyncio.wait_for(plugin.send(ref, "private prompt"), 1)
            events = plugin.events(ref)
            seen = [await asyncio.wait_for(anext(events), 1) for _ in range(3)]
            error = next(event for event in seen if event.kind == "error")
            status = next(
                event
                for event in seen
                if event.kind == "status" and event.payload["status"] == "error"
            )
            assert error.kind == "error"
            assert "api_key_expired" in error.payload["message"]
            assert len(error.payload["message"]) <= 2048
            assert status.kind == "status" and status.payload["status"] == "error"
            await events.aclose()
        finally:
            await plugin.close()

    asyncio.run(run())


def test_rpc_failure_emits_error_and_preserves_exception(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setenv("FAKE_PI_RPC_FAILURE", "1")
        plugin = PiRpcPlugin(FAKE, state_dir=tmp_path / "state")
        ref = await plugin.start(_spec(tmp_path))
        try:
            with pytest.raises(RuntimeError, match="api_key_expired"):
                await plugin.send(ref, "private prompt")
            events = plugin.events(ref)
            seen = [await asyncio.wait_for(anext(events), 1) for _ in range(2)]
            assert any(event.kind == "error" for event in seen)
            status = next(event for event in seen if event.kind == "status")
            assert status.payload["status"] == "error"
            await events.aclose()
        finally:
            await plugin.close()

    asyncio.run(run())


def test_startup_silence_reports_sanitized_stderr_and_error_status(
    tmp_path, monkeypatch
):
    async def run():
        monkeypatch.setenv("FAKE_PI_NO_OUTPUT", "1")
        plugin = PiRpcPlugin(FAKE, state_dir=tmp_path / "state")
        plugin._STARTUP_OUTPUT_TIMEOUT = 0.05
        ref = await plugin.start(_spec(tmp_path))
        try:
            await asyncio.wait_for(plugin.send(ref, "private prompt"), 1)
            events = plugin.events(ref)
            seen = [await asyncio.wait_for(anext(events), 1) for _ in range(2)]
            error = next(event for event in seen if event.kind == "error")
            status = next(event for event in seen if event.kind == "status")
            assert error.kind == "error"
            assert "api_key_expired" in error.payload["message"]
            assert "private prompt" not in error.payload["message"]
            assert status.kind == "status" and status.payload["status"] == "error"
            await events.aclose()
        finally:
            await plugin.close()

    asyncio.run(run())


def test_unexpected_stdout_close_reports_stderr_and_finishes_turn(
    tmp_path, monkeypatch
):
    async def run():
        monkeypatch.setenv("FAKE_PI_CLOSE_STDOUT", "1")
        plugin = PiRpcPlugin(FAKE, state_dir=tmp_path / "state")
        ref = await plugin.start(_spec(tmp_path))
        process = plugin._processes[ref.session_id]
        try:
            try:
                await plugin.send(ref, "private prompt")
            except RuntimeError as exc:
                assert "Pi RPC process is not running" in str(exc)
            await asyncio.wait_for(process.wait(), 1)
            events = plugin.events(ref)
            seen = [await asyncio.wait_for(anext(events), 1) for _ in range(2)]
            assert [event.kind for event in seen] == ["error", "status"]
            assert "api_key_expired" in seen[0].payload["message"]
            assert seen[1].payload["status"] == "error"
            with pytest.raises(StopAsyncIteration):
                await anext(events)
            await events.aclose()
        finally:
            await plugin.close()

    asyncio.run(run())


def test_stop_clears_session_state_and_resume_resets_stopping(tmp_path):
    async def run():
        plugin = PiRpcPlugin(FAKE, state_dir=tmp_path / "state")
        ref = await plugin.start(_spec(tmp_path))
        sid = ref.session_id
        await plugin.stop(ref)
        assert sid not in plugin._stopping
        assert all(
            sid not in mapping
            for mapping in (
                plugin._processes,
                plugin._readers,
                plugin._stderr_readers,
                plugin._queues,
                plugin._pending,
                plugin._commands,
                plugin._specs,
                plugin._session_files,
                plugin._settled,
                plugin._running,
                plugin._stderr_tails,
                plugin._prompt_activity,
                plugin._prompts,
            )
        )
        await plugin.resume(ref)
        assert sid not in plugin._stopping
        await plugin.stop(ref)
        await plugin.close()

    asyncio.run(run())


def test_startup_orphan_sweep_stops_matching_process(tmp_path, monkeypatch):
    session_id = str(uuid.uuid4())
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    path = state_dir / f"{session_id}.json"
    path.write_text(
        json.dumps(
            {
                "pid": 4321,
                "process_group": 4321,
                "command": ["pi", "--mode", "rpc"],
                "started_at": "Mon Oct 20 10:00:00 2026",
            }
        )
    )
    calls = []

    async def identity(_pid):
        return "Mon Oct 20 10:00:00 2026", "pi --mode rpc"

    monkeypatch.setattr(PiRpcPlugin, "_process_identity", staticmethod(identity))

    def killpg(group, sig):
        if sig == 0:
            raise ProcessLookupError
        calls.append((group, sig))

    monkeypatch.setattr("varde_runner.plugins.pi_rpc.plugin.os.killpg", killpg)
    plugin = PiRpcPlugin(FAKE, state_dir=state_dir)
    assert asyncio.run(plugin.recover_orphans()) == set()
    assert calls
