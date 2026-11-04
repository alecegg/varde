from __future__ import annotations

import json
from pathlib import Path

import pytest
from varde_learn.loop.output.adapter import normalize_codex, read_raw
from varde_learn.loop.output.assertions import snapshot, verify
from varde_learn.loop.output.blocked import classify
from varde_learn.loop.output.paired import summarize


def test_claude_requires_successful_text_result_and_preserves_metadata(
    tmp_path: Path,
) -> None:
    stream, raw = tmp_path / "stream.json", tmp_path / "raw.json"
    stream.write_text(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "",
                "usage": {"input_tokens": 12},
                "total_cost_usd": 0.1,
            }
        )
    )
    value, _ = read_raw("claude", stream, raw)
    assert value["usage"] == {"input_tokens": 12}
    assert value["total_cost_usd"] == 0.1
    stream.write_text(
        json.dumps(
            {"type": "result", "subtype": "error", "is_error": True, "result": "failed"}
        )
    )
    with pytest.raises(ValueError, match="successful result"):
        read_raw("claude", stream, raw)


def test_lifecycle_order_preserves_edit_start_before_review_completion() -> None:
    events = [
        {"type": "turn.started"},
        {"type": "item.started", "item": {"type": "collab_tool_call", "id": "review"}},
        {"type": "item.started", "item": {"type": "file_change", "id": "edit"}},
        {
            "type": "item.completed",
            "item": {"type": "collab_tool_call", "id": "review", "status": "completed"},
        },
        {
            "type": "item.completed",
            "item": {"type": "file_change", "id": "edit", "status": "completed"},
        },
        {"type": "turn.completed"},
    ]
    parsed = normalize_codex("\n".join(json.dumps(event) for event in events))
    tools = parsed["messages"][0]["content"]
    assert [
        (tool["input"]["event_type"], tool["input"]["item"]["id"]) for tool in tools
    ] == [
        ("item.started", "review"),
        ("item.started", "edit"),
        ("item.completed", "review"),
        ("item.completed", "edit"),
    ]


def test_no_write_outside_reports_deleted_files(tmp_path: Path) -> None:
    (tmp_path / "allowed").mkdir()
    deleted = tmp_path / "temporary.txt"
    deleted.write_text("before")
    before = snapshot(tmp_path)
    deleted.unlink()
    results = verify(
        [{"kind": "no_write_outside", "allowed_paths": ["allowed"]}],
        tmp_path,
        "",
        before,
    )
    assert results[0]["passed"] is False


def test_blocked_classifier_handles_trace_and_setup_fixtures() -> None:
    assert classify(trace_error="sandbox denied write") == "sandbox_denial"
    assert classify(setup_error="fixture missing") == "fixture_setup_failure"
    assert (
        classify(trace={"type": "error", "message": "command not found"})
        == "unavailable_app"
    )
    assert classify(trace_error="ordinary failure") is None


def test_real_failure_outranks_blocked_inconclusive_run() -> None:
    report = summarize(
        [
            {
                "eval_id": "one",
                "config": "with_skill",
                "run": 1,
                "blocked": True,
                "outcome": "completed",
                "total_assertions": 0,
                "passed_assertions": 0,
            },
            {
                "eval_id": "one",
                "config": "without_skill",
                "run": 1,
                "blocked": False,
                "outcome": "failed",
                "total_assertions": 1,
                "passed_assertions": 0,
            },
        ]
    )
    assert report["status"] == "fail"
    assert report["cases"][0]["candidate"]["inconclusive_runs"] == 1
    assert report["cases"][0]["current"]["pass_rate"] == 0.0
