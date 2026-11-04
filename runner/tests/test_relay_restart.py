from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from varde_runner.relay import RelayCLI, RelayWorker

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("varde") is None, reason="varde is not on PATH"),
]


def invoke(working, *args, check=True):
    env = {**os.environ, "VARDE_WORKING_DIR": str(working)}
    return subprocess.run(  # noqa: S603 - Test invokes the relay CLI with controlled arguments.
        ["varde", *args],  # noqa: S607 - Test resolves the installed Varde CLI from PATH.
        cwd=working,
        env=env,
        capture_output=True,
        text=True,
        check=check,
    )


def bind(working, session):
    marker = invoke(working, "msg", "address", "new", "mailman").stdout.strip()
    invoke(
        working,
        "msg",
        "address",
        "bind",
        marker,
        "--harness",
        "codex",
        "--session",
        session,
    )
    return next(
        item["token_id"]
        for item in json.loads(
            invoke(working, "msg", "address", "list", "--json").stdout
        )["bindings"]
        if item["session_id"] == session
    )


async def wait_for_binding(cli, predicate):
    for _ in range(100):
        bindings = await cli.bindings()
        match = next((item for item in bindings if predicate(item)), None)
        if match is not None:
            return match
        await asyncio.sleep(0.05)
    raise AssertionError("mailman binding did not reach the expected session")


async def wait_for_worker_session(worker):
    for _ in range(100):
        if worker.session_id is not None:
            return worker.session_id
        await asyncio.sleep(0.05)
    raise AssertionError("worker did not finish binding its session")


def make_binding_stale(working, session):
    key = hashlib.sha256(session.encode()).hexdigest()
    path = working / ".cache" / "inbox" / "bindings" / f"codex-{key}.json"
    binding = json.loads(path.read_text())
    binding["last_seen"] = "2000-01-01T00:00:00Z"
    path.write_text(json.dumps(binding))


def test_worker_restart_takes_over_crashed_runner_binding(tmp_path):
    prior_token = bind(tmp_path, "runner-crashed")
    cli = RelayCLI(cwd=tmp_path)
    worker = RelayWorker(cli, object())

    async def restart_worker():
        task = asyncio.create_task(worker.run())
        session = await wait_for_worker_session(worker)
        binding = await wait_for_binding(
            cli, lambda item: item.get("session_id") == session
        )
        assert binding["token_id"] != prior_token
        events = (tmp_path / ".cache" / "inbox" / "events.jsonl").read_text()
        assert '"event":"supersede"' in events
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(restart_worker())


def test_shutdown_releases_runner_binding(tmp_path):
    cli = RelayCLI(cwd=tmp_path)
    worker = RelayWorker(cli, object())

    async def stop_service():
        task = asyncio.create_task(worker.run())
        await wait_for_worker_session(worker)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not any(
            item.get("address") == "mailman" for item in await cli.bindings()
        )

    asyncio.run(stop_service())


def test_overlapping_runner_starts_keep_latest_holder(tmp_path):
    cli = RelayCLI(cwd=tmp_path)

    class RecordingCLI(RelayCLI):
        def __init__(self, *, cwd: Path):
            super().__init__(cwd=cwd)
            self.statuses: list[str | None] = []

        async def wait(self, identity):
            response = await super().wait(identity)
            self.statuses.append(response.get("status"))
            return response

    old_cli = RecordingCLI(cwd=tmp_path)
    old_worker = RelayWorker(old_cli, object())
    new_worker = RelayWorker(cli, object())

    async def start_workers():
        old_task = asyncio.create_task(old_worker.run())
        old_session = await wait_for_worker_session(old_worker)
        old_binding = await wait_for_binding(
            cli, lambda item: item.get("session_id") == old_session
        )
        new_task = asyncio.create_task(new_worker.run())
        new_session = await wait_for_worker_session(new_worker)
        current = await wait_for_binding(
            cli, lambda item: item.get("session_id") == new_session
        )
        await asyncio.wait_for(old_task, timeout=5)
        assert old_worker.state == "stopped"
        assert "superseded" in old_cli.statuses
        assert (await cli.bindings()) == [current]
        assert current["session_id"] != old_binding["session_id"]
        new_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await new_task
        assert not any(
            item.get("address") == "mailman" for item in await cli.bindings()
        )

    asyncio.run(start_workers())


def test_dead_non_runner_binding_does_not_block_startup(tmp_path):
    bind(tmp_path, "human-session")
    make_binding_stale(tmp_path, "human-session")
    cli = RelayCLI(cwd=tmp_path)
    worker = RelayWorker(cli, object())

    async def start_worker():
        task = asyncio.create_task(worker.run())
        session = await wait_for_worker_session(worker)
        binding = await wait_for_binding(
            cli, lambda item: item.get("session_id") == session
        )
        assert binding["session_id"] != "human-session"
        assert (
            "refuse" not in (tmp_path / ".cache" / "inbox" / "events.jsonl").read_text()
        )
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(start_worker())


def test_non_runner_live_holder_refusal_has_clear_reason(tmp_path):
    token = bind(tmp_path, "human-session")
    relay_store = tmp_path / ".cache" / "inbox" / "relay"
    relay_store.mkdir(parents=True)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    (relay_store / "state.json").write_text(
        json.dumps(
            {
                "current_mailman": token,
                "mailman_started": {token: now},
                "mailman_instances": {token: "test"},
                "events": [{"event": "waiting", "token_id": token, "at": now}],
            }
        )
    )
    cli = RelayCLI(cwd=tmp_path)
    worker = RelayWorker(cli, object())
    assert asyncio.run(cli.status())["runner_relay"] == "up"
    asyncio.run(worker.run())
    snapshot = worker.snapshot()
    assert snapshot["state"] == "refused"
    assert "human-session" in snapshot["refusal"]
    assert any(
        item["session_id"] == "human-session" for item in asyncio.run(cli.bindings())
    )


def test_unbound_stale_mailman_status_does_not_block_startup(tmp_path):
    token = bind(tmp_path, "e2e-live-holder-test")
    relay_store = tmp_path / ".cache" / "inbox" / "relay"
    relay_store.mkdir(parents=True)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    state_path = relay_store / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "current_mailman": token,
                "mailman_started": {token: now},
                "mailman_instances": {token: "offline-test"},
                "events": [{"event": "waiting", "token_id": token, "at": now}],
            }
        )
    )
    asyncio.run(RelayCLI(cwd=tmp_path).unbind("e2e-live-holder-test"))
    cli = RelayCLI(cwd=tmp_path)
    status = asyncio.run(cli.status())
    assert status["mailman"] == "none"
    assert status["runner_relay"] == "up"
    worker = RelayWorker(cli, object())

    async def restart_worker():
        task = asyncio.create_task(worker.run())
        session = await wait_for_worker_session(worker)
        binding = await wait_for_binding(
            cli, lambda item: item.get("session_id") == session
        )
        assert binding["session_id"] == session
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)

    asyncio.run(restart_worker())


def test_bad_store_is_reported_without_touching_other_store(tmp_path):
    (tmp_path / ".cache" / "inbox").mkdir(parents=True)
    (tmp_path / ".cache" / "inbox" / "events.jsonl").write_text("not-json\n")
    result = invoke(tmp_path, "msg", "address", "list", "--json", check=False)
    assert result.returncode == 0
    assert json.loads(result.stdout)["bindings"] == []


def test_bind_refusal_exposes_last_store_reason(tmp_path):
    bind(tmp_path, "runner-prior")
    marker = invoke(tmp_path, "msg", "address", "new", "mailman").stdout.strip()
    refused = invoke(
        tmp_path,
        "msg",
        "address",
        "bind",
        marker,
        "--harness",
        "codex",
        "--session",
        "runner-next",
        check=False,
    )
    assert refused.returncode == 2
    assert "marker superseded by a newer marker" in refused.stderr
    events = [
        json.loads(line)
        for line in (tmp_path / ".cache/inbox/events.jsonl").read_text().splitlines()
    ]
    assert events[-1]["reason"] == "live-binding"
    assert (
        asyncio.run(RelayWorker(RelayCLI(cwd=tmp_path), object())._refusal_reason())
        == "live-binding"
    )


def test_status_surfaces_bad_store(tmp_path):
    from varde_workflow.slots import add_alias

    add_alias(tmp_path, "unbound-test")
    invoke(
        tmp_path,
        "msg",
        "send",
        "--from",
        "relay-test",
        "--to",
        "unbound-test",
        "--kind",
        "info",
        "old message",
    )
    messages = tmp_path / ".cache" / "inbox" / "messages.jsonl"
    rows = messages.read_text().splitlines()
    message = json.loads(rows[-1])
    message["ts"] = "2000-01-01T00:00:00Z"
    rows[-1] = json.dumps(message)
    messages.write_text("\n".join(rows) + "\n")

    assert asyncio.run(RelayCLI(cwd=tmp_path).status())["bad"] is True
