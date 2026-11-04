from __future__ import annotations

import contextlib
import datetime as datetime_module
import io
import itertools
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

FIXED_NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)
GOLDEN = Path(__file__).parent / "golden" / "addresses"


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls.fromtimestamp(FIXED_NOW.timestamp(), UTC)
        return value if tz is None else value.astimezone(tz)


def _prepare(working: Path, monkeypatch) -> None:
    working.mkdir(parents=True)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.setenv("PASEO_AGENT_ID", "paseo-fixed")
    monkeypatch.setenv("VARDE_AGENT_ID", "agent-fixed")
    monkeypatch.setenv("VARDE_HARNESS", "codex")
    monkeypatch.setenv("VARDE_RUNNER_ENDPOINT", "endpoint-fixed")
    monkeypatch.chdir(working)
    monkeypatch.setattr(datetime_module, "datetime", FixedDateTime)
    from varde_workflow import binding, inbox, relay_state
    from varde_workflow.commands import msg_prune

    ids = itertools.count(1)
    monkeypatch.setattr(binding, "datetime", FixedDateTime)
    monkeypatch.setattr(inbox, "datetime", FixedDateTime)
    monkeypatch.setattr(relay_state, "datetime", FixedDateTime)
    monkeypatch.setattr(msg_prune, "datetime", FixedDateTime)
    monkeypatch.setattr(relay_state.os, "getpid", lambda: 12345)
    monkeypatch.setattr(secrets, "token_hex", lambda _size: f"{next(ids):08x}")
    monkeypatch.setattr(secrets, "token_bytes", lambda size: bytes([next(ids)]) * size)
    # Keep the old workflow's deterministic random stream stable for these
    # compatibility goldens while IDs are now generated inside varde_data.
    issue = binding.BindingStore.issue
    redeem = binding.BindingStore.redeem

    def issue_with_fixture_source(self, *args, **kwargs):
        marker = issue(self, *args, **kwargs)
        next(ids)
        return marker

    def redeem_with_fixture_source(self, *args, **kwargs):
        result = redeem(self, *args, **kwargs)
        if result:
            for _ in range(3):
                next(ids)
        return result

    monkeypatch.setattr(binding.BindingStore, "issue", issue_with_fixture_source)
    monkeypatch.setattr(binding.BindingStore, "redeem", redeem_with_fixture_source)


def _cli(argv: list[str], root: Path) -> dict[str, object]:
    from varde_workflow.cli import run

    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = run(argv)
    return {"exit": code, "stdout": stdout.getvalue(), "stderr": stderr.getvalue()}


def _capture(
    name: str, classification: str, root: Path, value: dict[str, object]
) -> None:
    result = {"classification": classification, **value}
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    rendered = rendered.replace(str(root), "<TMP>")
    target = GOLDEN / f"{name}.json"
    if os.environ.get("VARDE_UPDATE_GOLDENS") == "1":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    assert target.read_text(encoding="utf-8") == rendered


def _stable_text(path: Path) -> str:
    """Order the `retired` keys, which production writes in set-iteration order."""
    text = path.read_bytes().decode("utf-8")
    if path.name != "state.json":
        return text
    state = json.loads(text)
    retired = state.get("retired")
    if isinstance(retired, dict):
        state["retired"] = dict(sorted(retired.items()))
    return json.dumps(state, separators=(",", ":"))


def _store(root: Path, paths: tuple[str, ...]) -> dict[str, object]:
    result: dict[str, object] = {}
    for relative in paths:
        path = root / relative
        candidates = (
            sorted(item for item in path.rglob("*") if item.is_file())
            if path.is_dir()
            else [path]
            if path.exists()
            else []
        )
        if not candidates:
            result[relative] = {"bytes": "", "mode": None}
        for candidate in candidates:
            result[str(candidate.relative_to(root))] = {
                "bytes": _stable_text(candidate),
                "mode": f"{candidate.stat().st_mode & 0o777:04o}",
            }
    return result


def test_address_cli_goldens(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    _prepare(working, monkeypatch)
    base = ["msg", "address"]
    marker = str(_cli([*base, "new", "worker"], tmp_path)["stdout"]).strip()
    output = {
        "new": {"exit": 0, "stdout": marker + "\n", "stderr": ""},
        "bind": _cli(
            [*base, "bind", marker, "--session", "session", "--harness", "claude"],
            tmp_path,
        ),
        "refresh": _cli(
            [*base, "refresh", "--session", "session", "--harness", "claude"], tmp_path
        ),
        "list": _cli([*base, "list", "--json"], tmp_path),
        "unbind": _cli([*base, "unbind", "worker"], tmp_path),
    }
    _capture(
        "cli",
        "unchanged",
        tmp_path,
        {
            "stdout_stderr": output,
            "store": _store(
                working,
                (
                    ".cache/inbox/bindings",
                    ".cache/inbox/addresses/worker/current",
                    ".cache/inbox/addresses/worker/tokens",
                    ".cache/inbox/events.jsonl",
                ),
            ),
        },
    )


def test_binding_and_slot_goldens(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    _prepare(working, monkeypatch)
    from varde_workflow.binding import BindingStore
    from varde_workflow.slots import add_alias, remove_alias

    store = BindingStore(working)
    first = store.issue("worker", now=FIXED_NOW)
    assert store.redeem(first, "s1", "claude", str(working), now=FIXED_NOW)
    second = store.issue("worker", now=FIXED_NOW + timedelta(seconds=1), supersede=True)
    superseded_bind = store.redeem(
        second, "s2", "claude", str(working), now=FIXED_NOW + timedelta(seconds=1)
    )
    refused = store.redeem(
        first, "s2", "claude", str(working), now=FIXED_NOW + timedelta(seconds=2)
    )
    expired = store.issue(
        "expired", now=FIXED_NOW - timedelta(days=2), ttl=timedelta(seconds=1)
    )
    expired_result = store.redeem(expired, "s3", "claude", str(working), now=FIXED_NOW)
    add_alias(working, "orchestrator-1", "plan-a")
    slot_after_add = _store(working, (".cache/inbox/slots/orchestrator-1.json",))
    remove_alias(working, "plan-a")
    _capture(
        "binding_slots",
        "unchanged",
        tmp_path,
        {
            "tokens": [first, second, expired],
            "supersede": refused,
            "superseded_bind": superseded_bind,
            "expired_bind": expired_result,
            "bindings": store.list_bindings(),
            "store": _store(
                working,
                (
                    ".cache/inbox/events.jsonl",
                    ".cache/inbox/slots/orchestrator-1.json",
                    ".cache/inbox/addresses/worker/current",
                ),
            ),
            "slot_after_add": slot_after_add,
        },
    )


def test_relay_command_goldens(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    _prepare(working, monkeypatch)
    from varde_workflow.binding import BindingStore
    from varde_workflow.inbox import append_message

    now = FIXED_NOW
    mailman = BindingStore(working)
    marker = mailman.issue("mailman", now=now, supersede=True)
    assert mailman.redeem(marker, "mailman-session", "claude", str(working), now=now)
    token_path = next(
        (working / ".cache/inbox/addresses/mailman/tokens").glob("*.json")
    )
    token_id = json.loads(token_path.read_text())["token_id"]
    worker_marker = mailman.issue("worker", now=now)
    assert mailman.redeem(
        worker_marker, "worker-session", "claude", str(working), now=now
    )
    append_message(
        "sender",
        "worker",
        "info",
        "due relay",
        working=working,
        now=now - timedelta(minutes=3),
    )
    output = {
        "once": _cli(
            ["msg", "relay", "--once", "--as", token_id, "--now", now.isoformat()],
            tmp_path,
        )
    }
    state = json.loads((working / ".cache/inbox/relay/state.json").read_text())
    action_id = state["leases"][0]["action_id"]
    output["renew"] = _cli(
        ["msg", "relay", "renew", action_id, "--now", now.isoformat()], tmp_path
    )
    output["confirm"] = _cli(
        [
            "msg",
            "relay",
            "confirm",
            action_id,
            "--result",
            "pushed",
            "--now",
            now.isoformat(),
        ],
        tmp_path,
    )
    output["duplicate_confirm"] = _cli(
        [
            "msg",
            "relay",
            "confirm",
            action_id,
            "--result",
            "pushed",
            "--now",
            now.isoformat(),
        ],
        tmp_path,
    )
    output["end"] = _cli(
        ["msg", "relay", "end", "--as", token_id, "--now", now.isoformat()], tmp_path
    )
    _capture(
        "relay_cli",
        "unchanged",
        tmp_path,
        {
            "stdout_stderr": output,
            "store": _store(working, (".cache/inbox/relay/state.json",)),
        },
    )


def test_prune_retire_goldens(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    _prepare(working, monkeypatch)
    from varde_workflow.binding import BindingStore
    from varde_workflow.inbox import append_message, record_delivery
    from varde_workflow.relay_state import heartbeat

    old_message = append_message(
        "sender",
        "old",
        "info",
        "old",
        working=working,
        now=FIXED_NOW - timedelta(days=2),
    )
    record_delivery(
        working,
        old_message.id or "",
        "old",
        "delivered",
        via="test",
        now=(FIXED_NOW - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
    )
    stale = BindingStore(working).issue("stale", now=FIXED_NOW - timedelta(days=2))
    BindingStore(working).redeem(
        stale,
        "stale-session",
        "claude",
        str(working),
        now=FIXED_NOW - timedelta(days=2),
    )
    heartbeat(working, "expired-token", "ended", FIXED_NOW - timedelta(days=2))
    state_path = working / ".cache/inbox/relay/state.json"
    state = json.loads(state_path.read_text())
    state["mailman_started"]["expired-token"] = (
        (FIXED_NOW - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    )
    state_path.write_text(json.dumps(state, separators=(",", ":")))
    prune = _cli(["msg", "prune"], tmp_path)
    retire = _cli(["msg", "retire", "closed"], tmp_path)
    _capture(
        "prune_retire",
        "unchanged",
        tmp_path,
        {
            "stdout_stderr": {"prune": prune, "retire": retire},
            "store": _store(
                working,
                (
                    ".cache/inbox/relay/state.json",
                    ".cache/inbox/addresses",
                    ".cache/inbox/bindings",
                ),
            ),
        },
    )


def test_torn_events_tail_golden(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    _prepare(working, monkeypatch)
    from varde_workflow.binding import BindingStore

    inbox = working / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    events = inbox / "events.jsonl"
    events.write_bytes(b'{"event":"before"}')
    marker = BindingStore(working).issue("worker", now=FIXED_NOW)
    assert BindingStore(working).redeem(
        marker, "torn-session", "claude", str(working), now=FIXED_NOW
    )
    _capture(
        "torn_events",
        "intentional-change",
        tmp_path,
        {"marker": marker, "store": _store(working, (".cache/inbox/events.jsonl",))},
    )


# Expected append fix: `b'{"event":"before"}\\n{"event":"bind","at":'
# b'"2026-10-22T12:00:00Z","address":"worker","session_key":"claude-'
# b'391b1ab89c5dcaf211b50a0bc466d1bfa65d74afd95cc1555452007dca9eb00a"}\\n'`.
# This fixture freezes the current concatenated bytes as an intentional change.
