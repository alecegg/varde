from __future__ import annotations

import datetime as datetime_module
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

FIXED_NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)
GOLDEN = (
    Path(__file__).parents[2] / "data" / "tests" / "golden" / "relay" / "basic.json"
)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls.fromtimestamp(FIXED_NOW.timestamp(), UTC)
        return value if tz is None else value.astimezone(tz)


def _json_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _store(working: Path) -> dict[str, object]:
    inbox = working / ".cache" / "inbox"
    roots = [
        inbox / "events.jsonl",
        inbox / "messages.jsonl",
        inbox / "deliveries.jsonl",
        inbox / "relay",
    ]
    files = sorted(
        item
        for root in roots
        for item in (root.rglob("*") if root.is_dir() else [root])
        if item.is_file()
    )
    return {
        str(path.relative_to(working)): {
            "bytes": path.read_bytes().decode("utf-8"),
            "mode": f"{path.stat().st_mode & 0o777:04o}",
        }
        for path in files
    }


def _run_step(  # noqa: C901, PLR0912, PLR0915 - fixture operation interpreter
    working: Path, step: dict[str, Any], symbols: dict[str, Any]
) -> Any:
    from varde_workflow.binding import BindingStore
    from varde_workflow.inbox import append_message, record_relay_event
    from varde_workflow.relay_state import (
        confirm,
        end,
        escalate_due,
        lease_actions,
        renew,
    )
    from varde_workflow.relay_wait import once, wait

    op = str(step["op"])
    args = step.get("args", {})

    def resolve(value: Any) -> Any:
        if not isinstance(value, str) or not value.startswith("$"):
            return value
        reference = value[1:].split(".")
        resolved = symbols[reference[0]]
        for part in reference[1:]:
            assert isinstance(resolved, dict)
            resolved = resolved[part]
        return resolved

    args = {key: resolve(value) for key, value in args.items()}
    now = _json_time(str(step["now"]))
    if op == "bind":
        store = BindingStore(working)
        address = str(args["address"])
        marker = store.issue(address, now=now, supersede=bool(args.get("supersede")))
        assert store.redeem(
            marker, str(args["session"]), "claude", str(working), now=now
        )
        token_path = store.addresses / address / "current"
        current = json.loads(token_path.read_text(encoding="utf-8"))
        result: Any = {"marker": marker, "token_id": current["token_id"]}
    elif op == "message":
        result = append_message(
            "sender",
            str(args["to"]),
            str(args.get("kind", "info")),
            str(args.get("text", "scripted")),
            working=working,
            now=now - timedelta(seconds=int(args.get("age_s", 240))),
        ).id
    elif op == "wait":
        tick = [now]

        def poll(seconds: float) -> None:
            tick[0] += timedelta(seconds=seconds)

        result = wait(working, str(args["token"]), 2, now=lambda: tick[0], poll=poll)
    elif op == "once":
        result = once(working, str(args["token"]), now)
    elif op == "lease":
        message_id = symbols[str(args["message_ref"])]
        result = lease_actions(
            working,
            [{"to": str(args["to"]), "message_ids": [message_id]}],
            str(args["token"]),
            now,
            lease_for=timedelta(seconds=int(args.get("lease_s", 300))),
        )
    elif op == "renew":
        result = renew(working, str(args["action"]), now)
    elif op == "confirm":
        result = confirm(working, str(args["action"]), str(args["result"]), now)
    elif op == "end":
        end(working, str(args["token"]), now)
        result = {"status": "ended"}
    elif op == "supersede":
        store = BindingStore(working)
        old = str(args["old_token"])
        marker = store.issue("mailman", now=now, supersede=True)
        assert store.redeem(
            marker, str(args["session"]), "claude", str(working), now=now
        )
        result = {
            "old_superseded": old
            != json.loads((store.addresses / "mailman/current").read_text())["token_id"]
        }
    elif op == "escalate":
        result = escalate_due(working, now)
    elif op == "record":
        record_relay_event(
            working,
            str(args["message"]),
            str(args["to"]),
            str(args["event"]),
            now=now,
            via="relay",
        )
        result = {"recorded": args["event"]}
    else:
        raise AssertionError(f"unknown scripted operation: {op}")
    if isinstance(result, dict):
        if "action_id" in result:
            symbols[str(step.get("id", op))] = result["action_id"]
        if result.get("actions"):
            symbols[str(step.get("id", op))] = result["actions"][0]["action_id"]
        if op == "bind":
            symbols[str(step.get("id", op))] = result
    if op == "message":
        symbols[str(step.get("id", op))] = result
    if op == "lease" and isinstance(result, list) and result:
        symbols[str(step.get("id", op))] = result[0]["action_id"]
    if op in {"wait", "once"} and isinstance(result, dict) and result.get("actions"):
        symbols[str(step.get("id", op))] = result["actions"][0]["action_id"]
    return result


def test_old_relay_script_golden(  # noqa: C901 - fixture harness
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("PASEO_AGENT_ID", "paseo-fixed")
    monkeypatch.setenv("VARDE_AGENT_ID", "agent-fixed")
    monkeypatch.setenv("VARDE_HARNESS", "codex")
    monkeypatch.setenv("VARDE_RUNNER_ENDPOINT", "endpoint-fixed")
    monkeypatch.setattr(datetime_module, "datetime", FixedDateTime)
    from varde_workflow import binding, inbox, relay_state

    fixture = json.loads(GOLDEN.read_text(encoding="utf-8"))
    ids = iter(fixture["seeds"]["token_stream"])
    monkeypatch.setattr(inbox, "datetime", FixedDateTime)
    monkeypatch.setattr(relay_state, "datetime", FixedDateTime)
    monkeypatch.setattr(relay_state.os, "getpid", lambda: 12345)
    monkeypatch.setattr(secrets, "token_hex", lambda _size: f"{next(ids):08x}")
    monkeypatch.setattr(secrets, "token_bytes", lambda size: bytes([next(ids)]) * size)

    # The old workflow stored relay state in separate atomic JSON writes. Keep
    # those temporary-name draws in this fixture's stream, without touching the
    # frozen output or adding random draws to repository operations.
    from varde_data.open import open_data
    from varde_workflow import relay_wait

    class AddressTokenStream:
        def __init__(self, repository):
            self.repository = repository

        def __getattr__(self, name):
            method = getattr(self.repository, name)
            if name not in {
                "begin_confirm",
                "end",
                "finish_confirm",
                "heartbeat",
                "lease_actions",
                "record_event",
                "return_mailman",
                "renew",
            }:
                return method

            def call(*args, **kwargs):
                if name in {"heartbeat", "end"}:
                    next(ids)
                    next(ids)
                result = method(*args, **kwargs)
                writes = 0
                if name == "lease_actions":
                    writes = 2 * len(result)
                elif name == "return_mailman":
                    writes = 1
                elif name == "renew" and result:
                    writes = 2
                elif name == "begin_confirm" and result.status.value in {
                    "begun",
                    "resume",
                    "unknown",
                }:
                    writes = 1
                elif name == "finish_confirm":
                    writes = 2
                elif name == "record_event":
                    writes = 2 if args and args[0] in {"escalated", "dropped"} else 1
                for _ in range(writes):
                    next(ids)
                return result

            return call

    def open_with_legacy_token_stream(working, config):
        data = open_data(working, config)
        data._domains["addresses"] = AddressTokenStream(data.addresses)
        return data

    monkeypatch.setattr("varde_data.open.open_data", open_with_legacy_token_stream)
    monkeypatch.setattr(relay_wait, "open_data", open_with_legacy_token_stream)

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

    cases = fixture["cases"]
    actual_cases = []
    for case in cases:
        working = tmp_path / str(case["name"])
        working.mkdir()
        monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
        monkeypatch.chdir(working)
        symbols: dict[str, Any] = {}
        steps = []
        for source in case["steps"]:
            step: dict[str, Any] = {
                key: source[key] for key in ("id", "op", "args", "now") if key in source
            }
            response = _run_step(working, step, symbols)
            steps.append({**step, "response": response, "store": _store(working)})
        actual_cases.append({"name": case["name"], "steps": steps})
    rendered_value = {
        "classification": "unchanged",
        "seeds": fixture["seeds"],
        "cases": actual_cases,
    }
    rendered = (
        json.dumps(rendered_value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
    rendered = rendered.replace(str(tmp_path), "<TMP>")
    if os.environ.get("VARDE_UPDATE_GOLDENS") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(rendered, encoding="utf-8")
    assert GOLDEN.read_text(encoding="utf-8") == rendered


# Future event-log append changes prefix a torn tail with `b"\n"`; this case
# freezes the old bytes, where the bind event is concatenated to the torn tail.
