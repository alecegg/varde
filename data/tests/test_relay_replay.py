"""Replay every frozen workflow relay operation through the data service.

References use ``$name`` for a prior result and ``$name.field`` for mapping
fields. ``message_ref`` names a prior message result directly. Each case starts
with empty repositories; responses and frozen workflow store bytes are checked
after every operation.
"""

from __future__ import annotations

import base64
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from varde_data.addresses import open_addresses
from varde_data.backends.files.messages import FilesMessages
from varde_data.messages import touch_relay_wake
from varde_data.records.addresses import ReaderContext
from varde_data.records.messages import NewMessage, RelayEvent
from varde_data.relay import RelayService

FIXTURE = Path(__file__).parent / "golden" / "relay" / "basic.json"


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _store(root: Path) -> dict[str, dict[str, Any]]:
    inbox = root / ".cache/inbox"
    roots = [
        inbox / "events.jsonl",
        inbox / "messages.jsonl",
        inbox / "deliveries.jsonl",
        inbox / "relay",
    ]
    paths = sorted(
        path
        for item in roots
        for path in (item.rglob("*") if item.is_dir() else [item])
        if path.is_file()
    )
    return {
        path.relative_to(root).as_posix(): {
            "bytes": path.read_bytes().decode("utf-8"),
            "mode": f"{path.stat().st_mode & 0o777:04o}",
        }
        for path in paths
    }


def _normalize(value: Any, root: Path) -> Any:
    if isinstance(value, str):
        return value.replace(str(root), "<TMP>")
    if isinstance(value, list):
        return [_normalize(item, root) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item, root) for key, item in value.items()}
    return value


def _resolve(value: Any, symbols: dict[str, Any]) -> Any:
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    parts = value[1:].split(".")
    resolved = symbols[parts[0]]
    for part in parts[1:]:
        assert isinstance(resolved, dict)
        resolved = resolved[part]
    return resolved


def _run_step(  # noqa: C901, PLR0912, PLR0915 - frozen fixture interpreter
    root: Path,
    step: dict[str, Any],
    symbols: dict[str, Any],
    service: RelayService,
    ids: Any,
) -> Any:
    op = str(step["op"])
    args = {
        key: _resolve(value, symbols) for key, value in step.get("args", {}).items()
    }
    now = _time(str(step["now"]))
    addresses, messages = service.addresses, service.messages
    if op == "bind":
        address = str(args["address"])
        marker = addresses.issue(
            address, now=now, supersede=bool(args.get("supersede"))
        )
        next(ids)  # Preserve the frozen workflow's fixture-source draw.
        context = ReaderContext(
            cwd=str(root),
            paseo_id="paseo-fixed",
            agent_id="agent-fixed",
            runner_harness="codex",
            runner_endpoint="endpoint-fixed",
        )
        assert addresses.redeem(
            marker, str(args["session"]), "claude", context, now=now
        )
        for _ in range(3):
            next(ids)
        result = {"marker": marker, "token_id": addresses.current_token(address)}
    elif op == "message":
        result = messages.append(
            NewMessage(
                "sender",
                str(args["to"]),
                str(args.get("kind", "info")),
                str(args.get("text", "scripted")),
                ts=_stamp(now - timedelta(seconds=int(args.get("age_s", 240)))),
            )
        ).id
        touch_relay_wake(root)
    elif op == "wait":
        tick = [now]
        mono = [0.0]

        def poll(seconds: float) -> None:
            tick[0] += timedelta(seconds=seconds)
            mono[0] += seconds

        waiter = RelayService(
            addresses,
            messages,
            now=lambda: tick[0],
            monotonic=lambda: mono[0],
            sleep=poll,
            instance_id="paseo-fixed:12345",
        )
        result = waiter.wait(str(args["token"]), 2, poll=poll)
    elif op == "once":
        result = service.once(str(args["token"]), now)
    elif op == "lease":
        message_id = symbols[str(args["message_ref"])]
        actions = addresses.lease_actions(
            [{"to": str(args["to"]), "message_ids": [message_id]}],
            str(args["token"]),
            now,
            lease_for=timedelta(seconds=int(args.get("lease_s", 300))),
        )
        result = [
            {
                **action.payload,
                "action_id": action.action_id,
                "address": action.address,
                "to": action.address,
                "message_ids": list(action.message_ids),
                "token_id": action.token_id,
                "status": action.status,
                "created_at": _stamp(action.created_at),
                "expires_at": _stamp(action.expires_at),
            }
            for action in actions
        ]
    elif op == "renew":
        result = service.renew(str(args["action"]), now)
    elif op == "confirm":
        result = service.confirm(str(args["action"]), str(args["result"]), now)
    elif op == "end":
        service.end(str(args["token"]), now)
        result = {"status": "ended"}
    elif op == "supersede":
        old = str(args["old_token"])
        marker = addresses.issue("mailman", now=now, supersede=True)
        next(ids)
        assert addresses.redeem(
            marker,
            str(args["session"]),
            "claude",
            ReaderContext(
                cwd=str(root),
                paseo_id="paseo-fixed",
                agent_id="agent-fixed",
                runner_harness="codex",
                runner_endpoint="endpoint-fixed",
            ),
            now=now,
        )
        for _ in range(3):
            next(ids)
        result = {"old_superseded": old != addresses.current_token("mailman")}
    elif op == "escalate":
        result = service.escalate_due(now)
    elif op == "record":
        messages.record_relay_event(
            RelayEvent(
                str(args["message"]),
                str(args["to"]),
                str(args["event"]),
                _stamp(now),
                via="relay",
            )
        )
        result = {"recorded": args["event"]}
    else:
        raise AssertionError(f"unknown fixture operation {op}")

    name = str(step.get("id", op))
    if op in {"bind", "message"}:
        symbols[name] = result
    elif op == "lease":
        if isinstance(result, list) and result and isinstance(result[0], dict):
            symbols[name] = result[0]["action_id"]
    elif isinstance(result, dict):
        if result.get("action_id"):
            symbols[name] = result["action_id"]
        else:
            actions = result.get("actions")
            if isinstance(actions, list) and actions:
                if isinstance(actions[0], dict):
                    symbols[name] = actions[0]["action_id"]
            elif op in {"wait", "once"}:
                symbols[name] = result
    return result


def test_relay_service_replays_all_frozen_steps(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PASEO_AGENT_ID", "paseo-fixed")
    monkeypatch.setenv("VARDE_AGENT_ID", "agent-fixed")
    monkeypatch.setenv("VARDE_HARNESS", "codex")
    monkeypatch.setenv("VARDE_RUNNER_ENDPOINT", "endpoint-fixed")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ids = iter(fixture["seeds"]["token_stream"])
    for case in fixture["cases"]:
        root = tmp_path / str(case["name"])
        root.mkdir()
        addresses = open_addresses(root, "files")
        messages = FilesMessages(root)
        service = RelayService(addresses, messages, instance_id="paseo-fixed:12345")
        symbols: dict[str, Any] = {}
        for step in case["steps"]:
            response = step["response"]
            expected_actions = (
                response
                if isinstance(response, list)
                else response.get("actions", [])
                if isinstance(response, dict)
                else []
            )
            expected_action = (
                expected_actions[0].get("action_id")
                if expected_actions and isinstance(expected_actions[0], dict)
                else None
            )
            expected_action_id = (
                expected_action if isinstance(expected_action, str) else None
            )
            expected_message_id = (
                response
                if step["op"] == "message" and isinstance(response, str)
                else None
            )
            if step["op"] == "escalate":
                message_store = step["store"].get(".cache/inbox/messages.jsonl", {})
                message_bytes = (
                    message_store.get("bytes", "")
                    if isinstance(message_store, dict)
                    else ""
                )
                rows = [json.loads(line) for line in message_bytes.splitlines()]
                if rows and rows[-1].get("from") == "relay":
                    expected_message_id = rows[-1]["id"]
            expected_token = (
                response.get("token_id") if isinstance(response, dict) else None
            )
            expected_token_id = (
                expected_token if isinstance(expected_token, str) else None
            )
            expected_marker_value = (
                response.get("marker") if isinstance(response, dict) else None
            )
            expected_marker = (
                expected_marker_value
                if isinstance(expected_marker_value, str)
                else None
            )
            if expected_marker:
                encoded = expected_marker.split()[2].rstrip("]")[4:]
                secret = base64.b32decode(encoded + "======")
                monkeypatch.setattr(
                    secrets, "token_bytes", lambda _size, value=secret: value
                )
            else:
                monkeypatch.setattr(
                    secrets, "token_bytes", lambda size: bytes([next(ids)]) * size
                )

            def fixture_hex(
                size: int,
                action: str | None = expected_action_id,
                message: str | None = expected_message_id,
                token: str | None = expected_token_id,
            ) -> str:
                return _fixture_hex(size, ids, action, message, token)

            monkeypatch.setattr(secrets, "token_hex", fixture_hex)
            result = _run_step(root, step, symbols, service, ids)
            normalized = _normalize(result, root.parent)
            assert normalized == step["response"], (case["name"], step["id"])
            actual_store = _normalize(_store(root), root.parent)
            assert actual_store == step["store"], (case["name"], step["id"])


def _fixture_hex(
    size: int,
    ids: Any,
    action_id: str | None,
    message_id: str | None,
    token_id: str | None,
) -> str:
    generated = f"{next(ids):08x}"
    if size == 8 and action_id is not None:
        return action_id
    if size == 8 and token_id is not None:
        return token_id
    if size == 4 and message_id is not None:
        return message_id[2:]
    return generated
