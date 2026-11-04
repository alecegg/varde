from __future__ import annotations

import json
from argparse import Namespace
from datetime import UTC, datetime, timedelta

from varde_workflow.commands.msg_prune import (
    _candidates,
    _pending_addresses,
    run,
    select_retirements,
)

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


def test_threshold_24h_keeps_recent_unbound_address() -> None:
    retired = select_retirements(
        {"old": NOW - timedelta(hours=24), "recent": NOW - timedelta(hours=23)},
        now=NOW,
        pending=set(),
        live=set(),
        concluded=set(),
        tokens=set(),
        current_token=None,
    )
    assert retired == {"addresses": {"old"}, "tokens": set()}


def test_keeps_current_mailman_token() -> None:
    retired = select_retirements(
        {},
        now=NOW,
        pending=set(),
        live=set(),
        concluded=set(),
        tokens={"old-token", "current-token"},
        current_token="current-token",  # noqa: S106 - fixture token proves current token is retained
    )
    assert retired["tokens"] == {"old-token"}


def test_skips_already_retired_address_and_token() -> None:
    selected = select_retirements(
        {
            "retired-address": NOW - timedelta(hours=24),
            "available-address": NOW - timedelta(hours=24),
        },
        now=NOW,
        pending=set(),
        live=set(),
        concluded=set(),
        tokens={"retired-token", "available-token"},
        current_token=None,
        retired={"retired-address", "mailman:retired-token"},
    )
    assert selected == {
        "addresses": {"available-address"},
        "tokens": {"available-token"},
    }


def test_protects_superseded_but_waiting_token_until_return_grace() -> None:
    retired = select_retirements(
        {},
        now=NOW,
        pending=set(),
        live=set(),
        concluded=set(),
        tokens={"waiting", "ended"},
        current_token="new",  # noqa: S106 - fixture token proves superseded token handling
        relay_events=[
            {
                "token_id": "waiting",
                "event": "waiting",
                "at": NOW.isoformat(),
                "expect_return_by": "",
            },
            {"token_id": "ended", "event": "ended", "at": NOW.isoformat()},
        ],
        live_tokens=set(),
    )
    assert retired["tokens"] == {"ended"}


def test_lists_ended_token_for_retirement() -> None:
    retired = select_retirements(
        {},
        now=NOW,
        pending=set(),
        live=set(),
        concluded=set(),
        tokens={"ended"},
        current_token=None,
        relay_events=[{"token_id": "ended", "event": "ended", "at": NOW.isoformat()}],
        live_tokens=set(),
    )
    assert retired["tokens"] == {"ended"}


def test_protects_token_with_live_binding() -> None:
    retired = select_retirements(
        {},
        now=NOW,
        pending=set(),
        live=set(),
        concluded=set(),
        tokens={"bound"},
        current_token=None,
        relay_events=[],
        live_tokens={"bound"},
    )
    assert retired["tokens"] == set()


def test_dry_run_does_not_write_state(tmp_path, capsys) -> None:
    state = tmp_path / ".cache/inbox/relay/state.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"mailman_started":{"old":"2026-10-20T00:00:00Z"}}')
    before = state.read_bytes()
    assert run(Namespace(dry_run=True), tmp_path) == 0
    assert state.read_bytes() == before
    assert json.loads(capsys.readouterr().out)["addresses"] == []


def test_messages_unchanged_when_pruning(tmp_path) -> None:
    inbox = tmp_path / ".cache/inbox"
    inbox.mkdir(parents=True)
    messages = inbox / "messages.jsonl"
    messages.write_text(
        json.dumps(
            {
                "id": "m1",
                "ts": "2026-10-20T00:00:00Z",
                "from": "main",
                "to": "old",
                "kind": "info",
                "text": "done",
            }
        )
        + "\n"
    )
    index = inbox / "index" / "old.json"
    index.parent.mkdir()
    index.write_text(json.dumps({"watermark": messages.stat().st_size}))
    before = messages.read_bytes()
    assert run(Namespace(dry_run=False), tmp_path) == 0
    assert messages.read_bytes() == before
    state = json.loads((inbox / "relay" / "state.json").read_text())
    assert "old" in state["retired"]


def test_delivered_alias_is_not_pending_after_slot_read(tmp_path) -> None:
    inbox = tmp_path / ".cache" / "inbox"
    (inbox / "slots").mkdir(parents=True)
    (inbox / "slots" / "orchestrator-1.json").write_text(
        json.dumps(
            {
                "slot": "orchestrator-1",
                "aliases": ["plan-a"],
                "current_address": "orchestrator-1",
            }
        )
    )
    message = {
        "id": "alias-message",
        "ts": NOW.isoformat(),
        "from": "main",
        "to": "plan-a",
        "kind": "info",
        "text": "delivered through slot",
    }
    log = inbox / "messages.jsonl"
    log.write_text(json.dumps(message) + "\n")
    index = inbox / "index" / "orchestrator-1.json"
    index.parent.mkdir()
    index.write_text('{"watermark":0}')
    alias_index = inbox / "index" / "plan-a.json"
    alias_index.write_text('{"watermark":0}')
    deliveries = inbox / "deliveries.jsonl"
    deliveries.write_text(
        json.dumps(
            {
                "message_id": "alias-message",
                "reader": "orchestrator-1",
                "event": "delivered",
                "via": "cli",
                "at": NOW.isoformat(),
            }
        )
        + "\n"
    )

    assert _pending_addresses(tmp_path, {"plan-a"}) == set()


def test_concluded_message_address_is_a_prune_candidate(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VARDE_DATA_MESSAGES_BACKEND", "files")
    monkeypatch.setenv("VARDE_DATA_ADDRESSES_BACKEND", "files")
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    messages = open_data(tmp_path, load_data_config()).messages
    messages.mark_concluded("completed-address")

    selected = _candidates(tmp_path, NOW)

    assert selected["addresses"] == {"completed-address"}
