from __future__ import annotations

import datetime as datetime_module
import itertools
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

FIXED_NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)
GOLDEN = Path(__file__).parent / "golden" / "msg" / "hook.json"


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls.fromtimestamp(FIXED_NOW.timestamp(), UTC)
        return value if tz is None else value.astimezone(tz)


def _prepare(working: Path, monkeypatch) -> None:
    working.mkdir(parents=True)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(working)
    monkeypatch.setattr(datetime_module, "datetime", FixedDateTime)
    from varde_workflow import inbox

    ids = itertools.count(1)
    monkeypatch.setattr(inbox, "datetime", FixedDateTime)
    monkeypatch.setattr(secrets, "token_hex", lambda _size: f"{next(ids):08x}")
    from varde_workflow.binding import BindingStore

    issue = BindingStore.issue
    redeem = BindingStore.redeem

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

    monkeypatch.setattr(BindingStore, "issue", issue_with_fixture_source)
    monkeypatch.setattr(BindingStore, "redeem", redeem_with_fixture_source)


def _bytes(path: Path) -> str:
    return path.read_bytes().decode("utf-8") if path.exists() else ""


def test_hook_claim_and_receipt_golden(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    _prepare(working, monkeypatch)
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    from varde.glue.inbox_hook import prompt_inbox
    from varde_workflow.binding import BindingStore
    from varde_workflow.inbox import append_message
    from varde_workflow.relay_state import lease_actions

    binding = BindingStore(working)
    marker = binding.issue("worker", now=FIXED_NOW)
    assert binding.redeem(marker, "session", "claude", str(working), now=FIXED_NOW)
    leased = append_message(
        "sender", "worker", "info", "leased mail", working=working, now=FIXED_NOW
    )
    unleased = append_message(
        "sender", "worker", "info", "hook delivery", working=working, now=FIXED_NOW
    )
    action = lease_actions(
        working,
        [{"to": "worker", "message_ids": [leased.id]}],
        "mailman-token",
        FIXED_NOW,
    )[0]
    receipt = f"[varde-delivery: {action['action_id']} worker]"
    output = prompt_inbox(
        "claude",
        json.dumps({"session_id": "session", "prompt": receipt}).encode(),
        now=FIXED_NOW,
        banner_enabled=False,
    )
    inbox = working / ".cache" / "inbox"
    rendered = (
        json.dumps(
            {
                "classification": "unchanged",
                "stdout_lines": output,
                "claimed_id": unleased.id,
                "store": {
                    ".cache/inbox/messages.jsonl": _bytes(inbox / "messages.jsonl"),
                    ".cache/inbox/deliveries.jsonl": _bytes(inbox / "deliveries.jsonl"),
                    ".cache/inbox/index/worker.json": _bytes(
                        inbox / "index" / "worker.json"
                    ),
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    rendered = rendered.replace(str(tmp_path), "<TMP>")
    if os.environ.get("VARDE_UPDATE_GOLDENS") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(rendered, encoding="utf-8")
    assert GOLDEN.read_text(encoding="utf-8") == rendered
