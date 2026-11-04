from __future__ import annotations

import json
from pathlib import Path

import pytest
from varde.glue import session_notes
from varde_learn.knowledge.memory_config import Config


def _environment(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    working = tmp_path / "working"
    config = tmp_path / "config"
    working.mkdir()
    config.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    return working.resolve(), config / "sessions"


def test_reserve_session_is_stable_and_rejects_unbounded_ids(
    monkeypatch, tmp_path: Path
) -> None:
    working, state = _environment(monkeypatch, tmp_path)

    first = session_notes.reserve_session("codex", "session one")
    second = session_notes.reserve_session("codex", "session one")

    assert first == second
    assert first is not None and first.parent.parent == working / "session-notes"
    assert list(state.glob("*.json"))
    assert session_notes.reserve_session("codex", "x" * 257) is None


def test_nudge_fires_only_on_upward_threshold_crossing(
    monkeypatch, tmp_path: Path
) -> None:
    _environment(monkeypatch, tmp_path)
    config = Config.from_toml("[session]\nnotes_at_tokens = 10\n")

    under = json.dumps(
        {"usage": {"input": 9}, "model": {"contextWindow": 100}}
    ).encode()
    over = json.dumps(
        {"usage": {"input": 10}, "model": {"contextWindow": 100}}
    ).encode()

    assert session_notes.nudge("pi", "abc", under, config) is None
    reserved = session_notes.reserve_session("pi", "abc")
    message = session_notes.nudge("pi", "abc", over, config)
    assert message is not None
    assert message.startswith("Context reached 10 tokens (threshold 10).")
    assert (
        f"Main/interactive sessions: create or refresh the session note at {reserved}"
        in message
    )
    assert "the user compacts" in message
    assert "Orchestrators: write HANDOFF.md" in message
    assert "send the handoff to main per varde-orchestrate" in message
    assert session_notes.nudge("pi", "abc", over, config) is None
    assert session_notes.nudge("pi", "abc", under, config) is None
    assert "Context reached 10 tokens" in (
        session_notes.nudge("pi", "abc", over, config) or ""
    )


def test_threshold_uses_90_percent_of_context_window(
    monkeypatch, tmp_path: Path
) -> None:
    _environment(monkeypatch, tmp_path)
    config = Config()

    window_under = json.dumps(
        {"usage": {"input": 89}, "model": {"contextWindow": 100}}
    ).encode()
    window_at = json.dumps(
        {"usage": {"input": 90}, "model": {"contextWindow": 100}}
    ).encode()
    default_under = json.dumps({"usage": {"input": 199_999}}).encode()
    default_at = json.dumps({"usage": {"input": 200_000}}).encode()

    assert session_notes.nudge("pi", "window", window_under, config) is None
    assert "threshold 90" in (
        session_notes.nudge("pi", "window", window_at, config) or ""
    )

    assert session_notes.nudge("pi", "default", default_under, config) is None
    assert "threshold 200000" in (
        session_notes.nudge("pi", "default", default_at, config) or ""
    )


def test_pipeline_worker_uses_role_threshold_and_handoff_rule(
    monkeypatch, tmp_path: Path
) -> None:
    _environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        session_notes, "_pipeline_binding", lambda *_: ("builder", "plan")
    )
    config = Config.from_toml("[session]\nnotes_at_tokens = 10\n")
    under = json.dumps({"usage": {"input": 249_999}}).encode()
    at = json.dumps({"usage": {"input": 250_000}}).encode()

    assert session_notes.nudge("pi", "worker", under, config) is None
    message = session_notes.nudge("pi", "worker", at, config)

    assert message is not None
    assert "threshold 250000" in message
    assert "structured checkpoint" in message
    assert "turn limit is 60" in message
    assert "350000 tokens" in message


def test_reserved_session_persists_note_path_for_the_session(
    monkeypatch, tmp_path: Path
) -> None:
    working, state = _environment(monkeypatch, tmp_path)
    note = session_notes.reserve_session("codex", "session-42")
    assert note == session_notes.reserve_session("codex", "session-42")
    assert note is not None
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("Next: inspect the failing route.\n", encoding="utf-8")
    record = json.loads(next(state.glob("*.json")).read_text(encoding="utf-8"))
    assert record["session_id"] == "session-42"
    assert Path(record["notes_path"]) == note
    assert note.read_text(encoding="utf-8") == "Next: inspect the failing route.\n"
    assert note.is_relative_to(working / "session-notes")


def _pipeline_record(session_id: str, role: str, turn: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": session_id,
        "harness": "codex",
        "role": role,
        "turn": turn,
        "current_item": "task-a",
        "worktree": "/worktrees/task-a",
        "branch": "task-a",
        "last_commit": "abc123",
        "queue_position": 1,
        "decisions_made": [],
        "pending_findings": [],
        "next_actions": ["continue task-a"],
        "files_touched": [],
        "token_usage": {"status": "unavailable", "cumulative_tokens": None},
    }


def test_pipeline_turn_prompt_names_the_structured_record(
    monkeypatch, tmp_path: Path
) -> None:
    _environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        session_notes, "_pipeline_binding", lambda *_: ("builder", "plan")
    )

    first = session_notes.turn_prompt("codex", "worker")

    assert first is not None and "turn 1" in first
    assert "queue_position" in first and "plan-builder/latest.json" in first


def test_pipeline_turn_end_requires_checkpoint_then_persists_it(
    monkeypatch, tmp_path: Path
) -> None:
    _environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        session_notes, "_pipeline_binding", lambda *_: ("builder", "plan")
    )
    session_notes.turn_prompt("codex", "worker")
    notes = session_notes.reserve_session("codex", "worker")
    assert notes is not None

    blocked = session_notes.turn_end("codex", "worker", b"{}")
    assert blocked is not None and "cannot finish" in blocked

    from varde.glue import handoff_checkpoint

    root = session_notes._checkpoint_root("plan", "builder")
    assert root is not None
    handoff_checkpoint.write_checkpoint(root, _pipeline_record("worker", "builder", 1))
    assert session_notes.turn_end("codex", "worker", b"{}") is None
    latest = root / "latest.json"
    assert handoff_checkpoint.read_checkpoint(latest)["turn"] == 1


@pytest.mark.parametrize(
    ("role", "turn_count", "tokens", "reason"),
    [
        ("builder", 1, 250_000, "threshold"),
        ("reviewer", 60, 10, "turn-limit"),
        ("builder", 1, 350_000, "hard-stop"),
        ("orchestrator", 1, 400_000, "threshold"),
    ],
)
def test_pipeline_turn_end_prompts_handoff_after_checkpoint(  # noqa: PLR0913, PLR0917
    monkeypatch,
    tmp_path: Path,
    capsys,
    role: str,
    turn_count: int,
    tokens: int,
    reason: str,
) -> None:
    _environment(monkeypatch, tmp_path)
    monkeypatch.setattr(session_notes, "_pipeline_binding", lambda *_: (role, "plan"))
    notes = session_notes.reserve_session("codex", "worker")
    assert notes is not None
    session_notes._with_state(
        "codex",
        "worker",
        lambda state: state.update(turn_count=turn_count - 1),
    )
    session_notes.turn_prompt("codex", "worker")
    session_notes._with_state(
        "codex",
        "worker",
        lambda state: state.update(current_tokens=tokens),
    )

    from varde.glue import handoff_checkpoint

    root = session_notes._checkpoint_root("plan", role)
    assert root is not None
    handoff_checkpoint.write_checkpoint(
        root, _pipeline_record("worker", role, turn_count)
    )
    prompt = session_notes.turn_end("codex", "worker", b"{}")

    assert prompt is not None and reason in prompt
    assert "checkpoint" in prompt.lower()
    assert "transcript" not in prompt.lower()
    blocked_again = session_notes.turn_end("codex", "worker", b"{}")
    assert blocked_again is not None and reason in blocked_again
    from varde.fastpath import run as fastpath_run

    assert (
        fastpath_run(
            [
                "hook",
                "pipeline-handoff-complete",
                "--harness",
                "codex",
                "--session",
                "worker",
                "--turn",
                str(turn_count),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["completed"] is True
    assert session_notes.turn_end("codex", "worker", b"{}") is None


def test_pipeline_binding_skips_mailbox_lookup_when_runner_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from varde.glue import inbox_hook

    def fail(*_: object) -> str:
        raise AssertionError("resolve_address must not run")

    monkeypatch.setattr(inbox_hook, "runner_on", lambda: False)
    monkeypatch.setattr(inbox_hook, "resolve_address", fail)

    assert session_notes._pipeline_binding("claude", "s1") is None
