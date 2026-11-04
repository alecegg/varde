from __future__ import annotations

import json

import pytest
from varde_learn.loop.output import extract_tokens, extract_transcript
from varde_learn.loop.output.adapter import normalize_codex
from varde_learn.loop.output.command import (
    OutputRequest,
    _is_environment_limited,
    run_output,
)
from varde_learn.loop.output.run import write_run_artifacts
from varde_learn.loop.trigger import (
    CODEX,
    TriggerRequest,
    parse_claude,
    parse_opencode,
    run_trigger,
)


def test_extract_transcript_and_usage() -> None:
    value = {
        "messages": [
            {
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "tool_use"},
                    {"type": "text", "text": "second"},
                ]
            }
        ],
        "usage": {
            "input_tokens": 12,
            "output_tokens": "bad",
            "cache_read_input_tokens": 3,
        },
    }
    assert extract_transcript(value) == "first\nsecond"
    assert extract_tokens(value) == (True, 15)
    assert extract_transcript({"result": "answer", "messages": []}) == "answer"


def test_run_artifacts_write_transcripts_and_timing(tmp_path) -> None:
    timing = write_run_artifacts(
        tmp_path,
        {"result": "ok", "usage": {"input_tokens": 4}, "duration_ms": 22},
        harness="claude",
        model=None,
        outcome="completed",
        exit_code=0,
        timeout_seconds=10,
        elapsed_ms=30,
    )
    assert (tmp_path / "transcript.txt").read_text() == "ok"
    assert (tmp_path / "outputs/transcript.txt").read_text() == "ok"
    assert timing["tokens"] == 4 and timing["duration_ms"] == 22
    assert json.loads((tmp_path / "timing.json").read_text())["outcome"] == "completed"


def test_environment_limited_evals_are_excluded_from_output_and_scoring(
    tmp_path,
) -> None:
    skill = tmp_path / "skill"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text("skill")
    (skill / "evals/evals.json").write_text(
        json.dumps(
            {
                "skills": [],
                "evals": [
                    {"id": "included", "prompt": "run me"},
                    {
                        "id": "limited",
                        "prompt": "skip me",
                        "environment_limited": True,
                    },
                ],
            }
        )
    )
    calls = []

    def runner(call):
        calls.append(call)
        return {"result": "ok"}, 0, 0

    report = run_output(
        OutputRequest(
            skill_dir=skill, workspace=tmp_path / "workspace", no_baseline=True
        ),
        runner=runner,
    )

    assert [record.eval_id for record in report.records] == ["included"]
    assert len(calls) == 1
    assert calls[0].prompt.endswith("run me")
    assert report.excluded_ids == ["limited"]
    assert report.benchmark["excluded_ids"] == ["limited"]


def test_environment_limited_flag_must_be_boolean() -> None:
    assert _is_environment_limited({"id": "a"}) is False
    assert _is_environment_limited({"id": "a", "environment_limited": True}) is True
    with pytest.raises(
        ValueError, match="eval a environment_limited must be a boolean"
    ):
        _is_environment_limited({"id": "a", "environment_limited": 1})


def test_normalize_codex_replays_stream_and_rejects_trailing_event() -> None:
    trace = "\n".join(
        [
            json.dumps({"type": "thread.started"}),
            json.dumps({"type": "turn.started"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "hello"},
                }
            ),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 2}}),
        ]
    )
    assert normalize_codex(trace)["result"] == "hello"
    with pytest.raises(ValueError, match="after terminal"):
        normalize_codex(trace + '\n{"type":"warning"}')


def test_trigger_replays_recorded_transcripts(tmp_path) -> None:
    queries = tmp_path / "queries.json"
    queries.write_text('[{"query":"use skill","should_trigger":true}]')
    skill = tmp_path / "SKILL.md"
    skill.write_text("skill")
    trace = b"\n".join(
        [
            b'{"type":"thread.started","thread_id":"t"}',
            b'{"type":"turn.started"}',
            (
                b'{"type":"item.started","item":{"id":"c",'
                b'"type":"command_execution","command":"cat '
                + str(skill).encode()
                + b'","status":"in_progress"}}'
            ),
            (
                b'{"type":"item.completed","item":{"id":"c",'
                b'"type":"command_execution","command":"cat '
                + str(skill).encode()
                + b'","status":"completed","exit_code":0}}'
            ),
            b'{"type":"turn.completed"}',
        ]
    )
    report = run_trigger(
        TriggerRequest("sample", queries, CODEX, skill_path=skill),
        runner=lambda harness, query, query_number, timeout_seconds: (trace, b"", 0),
    )
    assert report.summary_line.endswith("codex_measure=implicit_read_proxy")
    assert not report.failed


def test_claude_and_opencode_trace_validation() -> None:
    claude = (
        b'{"type":"assistant","message":{"content":[{"type":"tool_use",'
        b'"name":"Skill","input":{"skill":"x"}}]}}\n'
        b'{"type":"result","subtype":"success","is_error":false}'
    )
    assert parse_claude(claude, "x") is True
    open_code = (
        b'{"type":"step_start","part":{"type":"step-start"}}\n'
        b'{"type":"tool_use","part":{"type":"tool","tool":"skill",'
        b'"state":{"status":"completed","input":{"id":"x"}}}}\n'
        b'{"type":"step_finish","part":{"type":"step-finish",'
        b'"reason":"stop"}}'
    )
    assert parse_opencode(open_code, "x") is True
    with pytest.raises(ValueError):
        parse_claude(b'{"type":"assistant","message":{"content":[]}}', "x")


def test_trigger_split_is_stratified_fixed_and_complete() -> None:
    from varde_learn.loop.trigger import Query, split_queries

    queries = [Query(f"pos {n}", True) for n in range(10)] + [
        Query(f"neg {n}", False) for n in range(10)
    ]
    train = split_queries(queries, "train")
    validation = split_queries(queries, "validation")
    assert split_queries(list(reversed(queries)), "train") == [
        item for item in reversed(queries) if item in train
    ]
    assert len(train) == 12 and len(validation) == 8
    assert sum(item.should_trigger for item in train) == 6
    assert {item.query for item in train + validation} == {q.query for q in queries}
    assert split_queries(queries, "all") == queries


def test_trigger_precision_recall_and_summary(tmp_path) -> None:
    from varde_learn.loop.trigger import precision_recall

    assert precision_recall([(True, True), (True, False), (False, True)]) == (
        "0.50",
        "0.50",
    )
    assert precision_recall([(False, False)]) == ("n/a", "n/a")
