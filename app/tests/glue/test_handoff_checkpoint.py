from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from varde.glue import handoff_checkpoint


def _record(turn: int = 1) -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": "session-1",
        "harness": "codex",
        "role": "builder",
        "turn": turn,
        "current_item": "p6-enforce-handoff",
        "worktree": "/worktrees/task",
        "branch": "p6-enforce-handoff",
        "last_commit": "abc123",
        "queue_position": 2,
        "decisions_made": ["Keep the checkpoint structured"],
        "pending_findings": ["Review the token ledger"],
        "next_actions": ["Continue the current item"],
        "files_touched": ["app/src/varde/glue/handoff_checkpoint.py"],
        "token_usage": {"status": "reported", "cumulative_tokens": 1234},
    }


def test_checkpoint_round_trips_machine_and_human_records(tmp_path: Path) -> None:
    record = _record()

    root = tmp_path / "checkpoints" / "slot"
    paths = handoff_checkpoint.write_checkpoint(root, record)

    assert json.loads(paths.machine.read_text(encoding="utf-8")) == record
    rendered = paths.human.read_text(encoding="utf-8")
    for value in ("Current item", "Queue position", "Pending findings", "abc123"):
        assert value in rendered
    assert handoff_checkpoint.read_checkpoint(paths.machine) == record
    assert handoff_checkpoint.read_checkpoint(root / "latest.json") == record


def test_checkpoint_history_keeps_each_turn(tmp_path: Path) -> None:
    root = tmp_path / "checkpoints" / "slot"
    handoff_checkpoint.write_checkpoint(root, _record(1))
    handoff_checkpoint.write_checkpoint(root, _record(2))

    session_hash = hashlib.sha256(b"session-1").hexdigest()[:16]
    history = root / "sessions" / session_hash
    assert (history / "turn-0001.json").is_file()
    assert (history / "turn-0002.json").is_file()
    assert handoff_checkpoint.read_checkpoint(history / "latest.json")["turn"] == 2


def test_resume_prompt_uses_checkpoint_record() -> None:
    prompt = handoff_checkpoint.resume_prompt(_record())

    assert "p6-enforce-handoff" in prompt
    assert "checkpoint" in prompt.lower()
    assert "transcript" not in prompt.lower()


def test_invalid_checkpoint_is_rejected() -> None:
    with pytest.raises(ValueError, match="queue_position"):
        handoff_checkpoint.validate_checkpoint({**_record(), "queue_position": "two"})


@pytest.mark.parametrize(
    ("role", "tokens", "turns", "expected"),
    [
        ("builder", 249_999, 59, None),
        ("builder", 250_000, 1, "threshold"),
        ("reviewer", 100, 60, "turn-limit"),
        ("builder", 350_000, 1, "hard-stop"),
        ("orchestrator", 399_999, 80, None),
        ("orchestrator", 400_000, 1, "threshold"),
    ],
)
def test_handoff_thresholds(role, tokens, turns, expected) -> None:
    assert handoff_checkpoint.handoff_reason(role, tokens, turns) == expected


def test_activity_cursor_counts_each_completed_turn_once() -> None:
    count, cursor = handoff_checkpoint.observe_activity(3, "event-2", "event-3")
    duplicate_count, duplicate_cursor = handoff_checkpoint.observe_activity(
        count, cursor, "event-3"
    )
    next_count, next_cursor = handoff_checkpoint.observe_activity(
        duplicate_count, duplicate_cursor, "event-4"
    )

    assert (count, cursor) == (4, "event-3")
    assert (duplicate_count, duplicate_cursor) == (4, "event-3")
    assert (next_count, next_cursor) == (5, "event-4")


def test_usage_ledger_uses_latest_cumulative_session_total(tmp_path: Path) -> None:
    path = tmp_path / "token-ledger.json"

    handoff_checkpoint.record_usage(path, "p6", "session-1", 100)
    handoff_checkpoint.record_usage(path, "p6", "session-1", 125)
    handoff_checkpoint.record_usage(path, "p6", "session-2", None)

    ledger = json.loads(path.read_text(encoding="utf-8"))
    assert ledger["p6"]["cumulative_tokens"] == 125
    assert ledger["p6"]["sessions"]["session-2"] == {"status": "unavailable"}
