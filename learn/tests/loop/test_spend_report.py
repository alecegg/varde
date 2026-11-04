import json
from datetime import date, datetime
from types import SimpleNamespace

from varde_learn.loop.review.report import render_report
from varde_learn.loop.review.spend import (
    build,
    prepare_session,
    read_previous,
    render,
    review_target,
    write_snapshot,
)
from varde_learn.loop.review.spend_compare import compare


def test_claude_subagent_spend_counts_only_its_source_transcript():
    records = [
        SimpleNamespace(
            anchor=SimpleNamespace(source_id=f"/projects/{session}.jsonl"),
            timestamp="2026-10-20T12:00:00Z",
            usage_record={"input_tokens": count},
            usage_last=None,
            usage_total=None,
            provider_message_id=session,
            transcript_id=f"transcript:{session}",
            model=None,
            tool_name=None,
        )
        for session, count in (("parent", 10), ("agent-child", 7))
    ]
    window = (
        datetime.fromisoformat("2026-10-20T00:00:00+00:00"),
        datetime.fromisoformat("2026-10-21T00:00:00+00:00"),
    )

    prepared = prepare_session(
        {"harness": "claude", "session_id": "agent-child", "records": records},
        window[0],
        window[1],
    )

    assert [row["input"] for row in prepared["usage_rows"]] == [7]


def test_spend_report_and_snapshot_are_redacted(tmp_path):
    record = SimpleNamespace(
        usage_record={
            "input_tokens": 10,
            "cache_read_input_tokens": 20,
            "output_tokens": 2,
        },
        usage_last=None,
        usage_total=None,
        timestamp="2026-10-23T10:00:00+00:00",
        model="test",
        provider_message_id="msg",
        transcript_id="transcript",
        tool_name="monitor",
        text_excerpt="planner task",
        context_size=30,
    )
    data = build(
        [
            {
                "harness": "claude",
                "session_id": "session",
                "records": [record],
                "first_prompt": "planner task",
                "project": "demo",
            }
        ],
        ["claude", "pi"],
    )
    section = render(data, compare(None, data["snapshot"]))
    report = render_report(
        {"setup": [], "project": []}, run_date=date(2026, 10, 23), token_spend=section
    )
    assert "## Token spend" in report
    assert "unattributed" in report
    assert (
        "By role" in report and "By session (top 10)" in report and "By plan" in report
    )
    assert "claude: 1 sessions, 1 per-call" in report
    assert "pi: no sessions in window" in report
    path = write_snapshot(tmp_path, "2026-10-23", data["snapshot"])
    saved = json.loads(path.read_text())
    assert saved["totals"]["calls"] == 1
    assert '"session_id"' not in path.read_text()
    assert saved["totals"]["weighted"] == 22
    assert saved["window"] == {"start": None, "end": None}


def test_findings_have_measured_shape_evidence_and_parent_attribution():
    def session(session_id, prompt, timestamp, input_tokens=10, parent=None, sub=False):
        record = SimpleNamespace(
            usage_record={"input_tokens": input_tokens, "output_tokens": 1},
            usage_last=None,
            usage_total=None,
            timestamp=timestamp,
            model="test",
            provider_message_id=session_id,
            transcript_id=session_id,
            tool_name=None,
            role="user",
            text_excerpt=prompt,
        )
        return {
            "harness": "codex",
            "session_id": session_id,
            "records": [record],
            "first_prompt": prompt,
            "project": "demo",
            "parent_session_id": parent,
            "is_subagent": sub,
        }

    data = build(
        [
            session(
                "review-a", "Review branch: feature-x", "2026-10-23T10:00:00+00:00"
            ),
            session(
                "review-b", "Review branch: feature-x", "2026-10-23T11:00:00+00:00"
            ),
            session(
                "parent",
                "Orchestrator plan id `2026-10-23-plan-one`",
                "2026-10-23T12:00:00+00:00",
            ),
            session(
                "child",
                "subtask",
                "2026-10-23T12:01:00+00:00",
                parent="parent",
                sub=True,
            ),
        ],
        ["codex", "pi"],
    )
    assert review_target("Review branch: feature-x") == "feature-x"
    repeated = next(
        item
        for item in data["findings"]["project"]
        if "Repeated review" in item["title"]
    )
    assert repeated["category"] == "project"
    assert "measured share" in repeated["title"]
    assert (
        "Risk:" in repeated["proposal"]
        and "not estimated savings" in repeated["proposal"]
    )
    assert [item["session_id"] for item in repeated["evidence"]] == ["review-b"]
    child = next(
        item for item in data["by_plan"] if item["name"] == "2026-10-23-plan-one"
    )
    assert child["sessions"] == 2


def test_plan_name_and_prompt_secret_are_redacted_from_snapshot(tmp_path):
    secret = "a" * 40
    record = SimpleNamespace(
        usage_record={"input_tokens": 1},
        usage_last=None,
        usage_total=None,
        timestamp="2026-10-23T10:00:00+00:00",
        model="test",
        provider_message_id="msg",
        transcript_id="transcript",
        tool_name=None,
    )
    data = build(
        [
            {
                "harness": "claude",
                "session_id": "s",
                "records": [record],
                "first_prompt": f"plans/2026-10-23-{secret}",
            }
        ],
        ["claude"],
    )
    path = write_snapshot(tmp_path, "2026-10-23", data["snapshot"])
    assert secret not in path.read_text()
    assert "[redacted:review]" in path.read_text()


def test_coverage_breaks_down_sessions_and_empty_harnesses():
    data = build(
        [{"harness": "claude", "session_id": "s", "records": []}],
        ["claude", "pi"],
    )
    section = render(data, compare(None, data["snapshot"]))
    assert "claude: 1 sessions" in section and "1 no usage data" in section
    assert "pi: no sessions in window" in section


def test_read_previous_skips_same_day_and_future_snapshots(tmp_path):
    snapshot = {
        "totals": {"weighted": 1},
        "window": {
            "start": "2026-10-22T00:00:00+00:00",
            "end": "2026-10-22T23:59:59+00:00",
        },
    }
    write_snapshot(tmp_path, "2026-10-22", {**snapshot, "totals": {"weighted": 22}})
    write_snapshot(tmp_path, "2026-10-23", {**snapshot, "totals": {"weighted": 23}})
    write_snapshot(tmp_path, "2026-10-24", {**snapshot, "totals": {"weighted": 24}})
    previous = read_previous(tmp_path, "2026-10-23")
    assert previous is not None
    assert previous["totals"]["weighted"] == 22
