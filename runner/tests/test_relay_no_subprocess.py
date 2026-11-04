from __future__ import annotations

import asyncio
import os
from pathlib import Path

from varde_runner.relay import DataRelay, RelayWorker


def test_data_relay_does_not_invoke_fake_varde(tmp_path: Path, monkeypatch):
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    record = tmp_path / "argv"
    fake = bin_path / "varde"
    fake.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{record}'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("VARDE_RUNNER_RELAY", "data")

    async def exercise():
        adapter = DataRelay(tmp_path)
        worker = RelayWorker(adapter, object())
        assert await worker._start_binding()
        assert worker.identity
        await worker._release()

    asyncio.run(exercise())
    assert not record.exists()


def test_cli_mode_constructs_relay_cli(tmp_path: Path, monkeypatch):
    import varde_runner.relay as relay_module

    class FakeCLI:
        async def status(self):
            return {"mailmen": []}

        async def bindings(self):
            return []

        async def issue_and_bind(self, session_id):
            return "identity"

        async def issue_and_bind_superseding(self, session_id):
            return "identity"

        async def wait(self, identity):
            return {"status": "superseded"}

        async def end(self, identity):
            return None

        async def unbind(self, session_id):
            return None

    constructed = []
    monkeypatch.setenv("VARDE_RUNNER_RELAY", "cli")
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))
    monkeypatch.setattr(
        relay_module,
        "RelayCLI",
        lambda: (constructed.append(True), FakeCLI())[1],
    )

    asyncio.run(RelayWorker(None, object()).run())

    assert constructed == [True]


def test_invalid_relay_mode_fails_loudly(monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_RELAY", "invalid")

    try:
        asyncio.run(RelayWorker(None, object()).run())
    except ValueError as exc:
        assert "VARDE_RUNNER_RELAY must be" in str(exc)
    else:
        raise AssertionError("invalid relay mode was accepted")


def test_stopped_service_wait_stops_worker_without_task_cancellation(tmp_path: Path):
    from varde_data.relay import Stopped

    adapter = DataRelay(tmp_path)

    def stop_wait(*args, **kwargs):
        raise Stopped

    adapter.service.wait = stop_wait
    worker = RelayWorker(adapter, object())

    asyncio.run(worker.run())

    assert worker.state == "stopped"
    assert worker.task is not None and not worker.task.cancelled()
