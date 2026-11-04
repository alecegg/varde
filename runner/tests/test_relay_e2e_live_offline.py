from __future__ import annotations

import asyncio
import runpy
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest
from varde_runner.relay import RelayCLI

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("varde") is None, reason="varde is not on PATH"),
]


def test_live_lifecycle_sequence_with_real_cli_and_fake_plugin() -> None:
    script: dict[str, Any] = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts" / "relay_e2e.py")
    )
    live_timeout = script["LIVE_TIMEOUT"]
    temp_root = Path(tempfile.mkdtemp(prefix="relay-e2e-offline-"))
    working = temp_root / "working"
    working.mkdir()
    cli = RelayCLI(cwd=working)
    plugin = script["FakeLivePlugin"]()
    first_task: asyncio.Task[None] | None = None
    holder: tuple[str, bytes | None] | None = None

    async def exercise() -> None:
        nonlocal first_task, holder
        try:
            script["_issue_recipient"](working, "e2e-idle", "fake-agent")
            first = script["RecordingWorker"](cli, script["_LiveAdapter"](plugin))
            first_task = asyncio.create_task(first.run())
            assert await script["wait_for_predicate"](
                lambda: first.session_id is not None,
                timeout=live_timeout,
                interval=0.05,
            )

            overlap = await asyncio.wait_for(
                script["_verify_live_runner_takeover"](cli, first, first_task, plugin),
                timeout=180,
            )
            first_task = None
            assert overlap["runner worker stops after supersede"]
            assert overlap["overlap binding belongs to second runner"]
            assert overlap["overlap cancellation releases binding"]

            holder = script["_bind_live_nonrunner"](working)
            assert holder is not None
            holder_session, previous_state = holder
            refusal = await asyncio.wait_for(
                script["_verify_live_nonrunner_refusal"](cli, plugin, holder_session),
                timeout=live_timeout,
            )
            assert refusal["live non-runner holder remains bound after refusal"]
            script["_require_live_nonrunner_holder"](refusal)
            await asyncio.wait_for(cli.unbind(holder_session), timeout=live_timeout)
            script["_restore_live_nonrunner_state"](working, previous_state)
            holder = None

            restart = await asyncio.wait_for(
                script["_live_restart_drill"](working, "a1b2c3d4", fake_plugin=True),
                timeout=300,
            )
            worker_log = (working / "restart-worker.log").read_text(errors="replace")[
                -3000:
            ]
            assert restart == {
                "restart drill: graceful stops release address": True,
                "restart drill: crash binding is taken over": True,
                "restart drill: no live-binding refusals": True,
                "restart drill: every worker starts": True,
            }, f"restart checks: {restart}; worker log: {worker_log}"
        finally:
            if first_task is not None and not first_task.done():
                first_task.cancel()
                with suppress(asyncio.CancelledError, TimeoutError):
                    await asyncio.wait_for(first_task, timeout=live_timeout)
            if holder is not None:
                holder_session, previous_state = holder
                try:
                    await asyncio.wait_for(
                        cli.unbind(holder_session), timeout=live_timeout
                    )
                finally:
                    script["_restore_live_nonrunner_state"](working, previous_state)

    try:
        asyncio.run(asyncio.wait_for(exercise(), timeout=600))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
