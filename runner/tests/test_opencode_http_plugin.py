from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest
from varde_runner.plugins import SessionSpec
from varde_runner.plugins.opencode_http.plugin import OpenCodeHttpPlugin

FAKE = Path(__file__).parent / "fakes" / "fake_opencode_http.py"
IDENTITY = ("fake-start", "python fake_opencode_http.py serve")


def _spec(cwd: Path) -> SessionSpec:
    return SessionSpec("openai", "model", "agent-42", str(cwd), mode_id="auto")


def _read_log(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_start_send_events_responses_usage_interrupt_resume_and_stop(  # noqa: PLR0915
    tmp_path, monkeypatch
):
    async def run():
        log = tmp_path / "requests.jsonl"
        env_file = tmp_path / "child-env.json"
        monkeypatch.setenv("FAKE_OPENCODE_LOG", str(log))
        monkeypatch.setenv("FAKE_OPENCODE_ENV_FILE", str(env_file))
        parent_credentials = {
            key: value
            for key, value in os.environ.items()
            if any(term in key.upper() for term in ("API_KEY", "OAUTH", "ACCESS_TOKEN"))
        }
        plugin = OpenCodeHttpPlugin(
            str(FAKE),
            state_dir=tmp_path / "state",
            identity_reader=lambda _pid: IDENTITY,
        )
        ref = await plugin.start(_spec(tmp_path))
        sid = ref.session_id
        server = plugin._servers[sid]
        try:
            env = json.loads(env_file.read_text())
            assert env["credential_values"] == parent_credentials
            assert env["agent"] == "agent-42"
            assert env["harness"] == "opencode-http"
            assert env["password"] is True
            assert env["xdg_data"] == os.environ.get("XDG_DATA_HOME")

            await plugin.send(ref, "hello exactly")
            usage = await plugin.usage(ref)
            assert usage is not None
            assert usage["cost"] == 0.02
            events = plugin.events(ref)
            found = [(await asyncio.wait_for(anext(events), 2)).kind for _ in range(6)]
            assert found == [
                "activity",
                "permission_requested",
                "question_requested",
                "question_requested",
                "usage",
                "status",
            ]

            await plugin.respond(ref, "per_fake", {"decision": "once"})
            await plugin.respond(ref, "per_fake", {"decision": "reject"})
            await plugin.respond(
                ref, "frm_fake", {"kind": "question", "answer": {"ok": True}}
            )
            await plugin.respond(ref, "frm_stale", {"kind": "question", "answer": {}})
            await plugin.respond(
                ref, "missing", {"kind": "permission", "decision": "always"}
            )
            await plugin.interrupt(ref)
            terminal = await asyncio.wait_for(anext(events), 2)
            assert terminal.kind == "session_end"
            await events.aclose()
            records = _read_log(log)
            assert (
                sum(record["path"].endswith("/per_fake/reply") for record in records)
                == 1
            )
            assert not any("/missing/reply" in record["path"] for record in records)
            assert any(record["path"].endswith("/frm_fake/reply") for record in records)
            assert any(
                record["method"] == "DELETE" and record["path"].endswith("/frm_stale")
                for record in records
            )
            assert any(record["path"].endswith("/interrupt") for record in records)
            paths = [record["path"] for record in records]
            assert paths.index("/api/event") < paths.index(
                "/api/session/ses_fake/prompt"
            )
            state = json.loads(plugin._path(sid).read_text())
            assert "password" not in state

            await plugin.resume(ref)
            usage = await plugin.usage(ref)
            assert usage is not None
            assert usage["tokens"]["input"] == 8
            await plugin.stop(ref)
            await asyncio.wait_for(server["process"].wait(), 5)
            assert not plugin._path(sid).exists()
        finally:
            await plugin.stop(ref)

    asyncio.run(run())


@pytest.mark.parametrize(
    ("version", "missing_route", "message"),
    [
        ("2.0.17", False, "version 2.0.17 unsupported"),
        ("3.0.0", False, "version 3.0.0 unsupported"),
        ("2.0.18", True, "missing required routes"),
    ],
)
def test_startup_rejects_unsupported_server_api(
    tmp_path, monkeypatch, version, missing_route, message
):
    async def run():
        monkeypatch.setenv("FAKE_OPENCODE_VERSION", version)
        monkeypatch.setenv("FAKE_OPENCODE_MISSING_ROUTE", "1" if missing_route else "")
        plugin = OpenCodeHttpPlugin(
            str(FAKE),
            state_dir=tmp_path / "state",
            identity_reader=lambda _pid: IDENTITY,
        )
        with pytest.raises(RuntimeError, match=message):
            await plugin.start(_spec(tmp_path))
        assert not list((tmp_path / "state").glob("*.json"))

    asyncio.run(run())


def test_explicit_recovery_kills_only_matching_persisted_process(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    matching_id, stale_id = str(uuid.uuid4()), str(uuid.uuid4())
    common = {"owner_pid": 99999999, "owner_identity": None, "session_id": "ses_old"}
    matching = {
        **common,
        "pid": 123,
        "identity": ["start-a", "opencode serve"],
        "command": "opencode serve",
    }
    stale = {
        **common,
        "pid": 456,
        "identity": ["start-old", "opencode serve"],
        "command": "opencode serve",
    }
    (state_dir / f"{matching_id}.json").write_text(json.dumps(matching))
    (state_dir / f"{stale_id}.json").write_text(json.dumps(stale))
    identities = {
        123: ("start-a", "opencode serve"),
        456: ("start-new", "opencode serve"),
    }
    killed = []

    async def fake_terminate(pid):
        killed.append(pid)

    monkeypatch.setattr(
        "varde_runner.plugins.opencode_http.plugin._terminate_process_group",
        fake_terminate,
    )

    async def recover():
        plugin = OpenCodeHttpPlugin(
            "opencode", state_dir=state_dir, identity_reader=identities.get
        )
        await plugin.recover_orphans()

    asyncio.run(recover())
    assert killed == [123]
    for session_id in (matching_id, stale_id):
        record = json.loads((state_dir / f"{session_id}.json").read_text())
        assert record["pid"] is None


def test_resume_restarts_persisted_session_after_owner_exit(tmp_path):
    async def run():
        state = tmp_path / "state"
        first = OpenCodeHttpPlugin(
            str(FAKE), state_dir=state, identity_reader=lambda _pid: IDENTITY
        )
        ref = await first.start(_spec(tmp_path))
        old = first._servers[ref.session_id]
        try:
            record_path = first._path(ref.session_id)
            record = json.loads(record_path.read_text())
            record["owner_pid"] = 99999999
            record["owner_identity"] = None
            record_path.write_text(json.dumps(record))
            second = OpenCodeHttpPlugin(
                str(FAKE),
                state_dir=state,
                identity_reader=lambda pid: None if pid == 99999999 else IDENTITY,
            )
            await second.recover_orphans()
            resumed = await second.resume(ref)
            assert resumed == ref
            assert second._servers[ref.session_id]["pid"] != old["pid"]
            usage = await second.usage(ref)
            assert usage is not None
            assert usage["cost"] == 0.02
            await second.stop(ref)
        finally:
            await first.stop(ref)

    asyncio.run(run())


def test_prerelease_and_malformed_versions_fail_closed():
    from varde_runner.plugins.opencode_http.plugin import _version

    for version in ("2.0.18-rc.1", "not-a-version"):
        with pytest.raises(ValueError):
            _version(version)


def test_sse_reconnect_resubscribes_and_reconciles_pending_requests(
    tmp_path, monkeypatch
):
    async def run():
        log = tmp_path / "requests.jsonl"
        monkeypatch.setenv("FAKE_OPENCODE_LOG", str(log))
        monkeypatch.setenv("FAKE_OPENCODE_DISCONNECT_ONCE", "1")
        plugin = OpenCodeHttpPlugin(
            str(FAKE),
            state_dir=tmp_path / "state",
            identity_reader=lambda _pid: IDENTITY,
        )
        ref = await plugin.start(_spec(tmp_path))
        try:
            await plugin.send(ref, "after initial connected frame")
            event = await asyncio.wait_for(anext(plugin.events(ref)), 5)
            assert event.kind == "activity"
            records = _read_log(log)
            assert sum(record["path"] == "/api/event" for record in records) >= 2
            assert (
                sum(record["path"] == "/api/permission/request" for record in records)
                >= 2
            )
            assert sum(record["path"] == "/api/form" for record in records) >= 2
        finally:
            await plugin.stop(ref)

    asyncio.run(run())
