import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_data.locking import file_lock
from varde_learn.loop.review import run as review_run
from varde_learn.loop.review.ledger import read_index
from varde_learn.loop.review.run import _window


def _row(path: Path, session_id: str = "s1"):
    return {
        "harness": "codex",
        "session_id": session_id,
        "path": str(path),
        "root": str(path.parent),
        "status": "analyzable",
        "kind": "main",
        "cwd": str(path.parent),
        "project": "test",
    }


def _inventory(monkeypatch, rows, statuses=None):
    monkeypatch.setattr("varde_learn.loop.sources.load_locations", list)
    monkeypatch.setattr(
        review_run,
        "build_inventory",
        lambda *_args: SimpleNamespace(
            sessions=[dict(row) for row in rows], statuses=statuses or [], locations=[]
        ),
    )


def _fake_runner(calls, *, finding=False):
    def run(_command, *, input, **_kwargs):
        calls.append(input)
        if "Synthesize" in input:
            findings = {"setup": [], "project": []}
            if finding:
                findings["project"] = [
                    {
                        "title": "Improve retries",
                        "proposal": "Retry safely",
                        "evidence": [
                            {"harness": "codex", "session_id": "s1", "anchor": 0}
                        ],
                    }
                ]
            result = json.dumps({"findings": findings})
        else:
            result = "one observation"
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"result": result, "usage": {"input_tokens": 20, "output_tokens": 1}}
            ),
            stderr="",
        )

    return run


def test_yesterday_and_explicit_date_are_utc_days():
    now = datetime(2026, 10, 23, 12, tzinfo=UTC)
    start, end = _window("yesterday", Path("."), now)
    assert start.isoformat() == "2026-10-22T00:00:00+00:00"
    assert end.date().isoformat() == "2026-10-22"
    start, end = _window("2026-10-20", Path("."), now)
    assert start.isoformat() == "2026-10-20T00:00:00+00:00"
    assert end.date().isoformat() == "2026-10-20"
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _window("20261020", Path("."), now)


def test_since_last_uses_last_success_and_caps_at_seven_days(tmp_path):
    store = tmp_path / "store"
    old = datetime(2026, 10, 1, tzinfo=UTC)
    review_run.mark_review_row(
        store,
        {
            "harness": "review",
            "session_id": "run",
            "status": "complete",
            "source": "review",
            "run_at": old.isoformat(),
        },
        latest_by_key={},
    )
    now = datetime(2026, 10, 23, 12, tzinfo=UTC)
    start, end = _window("since-last", store, now)
    assert start == now - timedelta(days=7)
    assert end == now
    recent = datetime(2026, 10, 22, 6, 30, tzinfo=UTC)
    review_run.mark_review_row(
        store,
        {
            "harness": "review",
            "session_id": "recent",
            "status": "complete",
            "source": "review",
            "run_at": recent.isoformat(),
        },
        latest_by_key=read_index(store),
    )
    start, end = _window("since-last", store, now)
    assert start == recent
    assert end == now


def test_model_orchestration_skips_unchanged_session(monkeypatch, tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("{}\n")
    _inventory(monkeypatch, [_row(transcript)])
    monkeypatch.setattr(review_run, "_inspect", lambda _row: (["record"], {"turns": 1}))
    monkeypatch.setattr(
        review_run, "build_digest", lambda records, _cap: "digest:" + ",".join(records)
    )
    calls = []
    runner = _fake_runner(calls)
    store = tmp_path / "store"
    first = review_run.run_review(store_dir=store, runner=runner)
    second = review_run.run_review(store_dir=store, runner=runner)
    assert first["coverage"]["analyzed"] == 1
    assert second["sessions"][0]["reason"] == "already reviewed"
    assert len(calls) == 2  # extraction and synthesis only on first run
    assert read_index(store)[("codex", "s1")]["source"] == "review"


def test_growth_requeues_by_key_and_uses_resume_position(monkeypatch, tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("one\n")
    _inventory(monkeypatch, [_row(transcript)])
    inspections = iter(
        [(["old", "new"], {"turns": 2}), (["old", "new", "newer"], {"turns": 3})]
    )
    monkeypatch.setattr(review_run, "_inspect", lambda _row: next(inspections))
    monkeypatch.setattr(
        review_run, "build_digest", lambda records, _cap: "|".join(records)
    )
    calls = []
    runner = _fake_runner(calls)
    store = tmp_path / "store"
    review_run.run_review(store_dir=store, runner=runner)
    transcript.write_text("one\ntwo\n")
    review_run.run_review(store_dir=store, runner=runner)
    extraction_prompts = [prompt for prompt in calls if "Synthesize" not in prompt]
    prompt_prefix = (
        "varde-daily-review: Extract actionable observations as JSON "
        "from this session digest:\n"
    )
    assert extraction_prompts == [
        prompt_prefix + "old|new",
        prompt_prefix + "newer",
    ]


def test_budget_exhaustion_keeps_tail_pending(monkeypatch, tmp_path):
    rows = []
    for session_id in ("a", "b", "c"):
        path = tmp_path / f"{session_id}.jsonl"
        path.write_text("one\n")
        rows.append(_row(path, session_id))
    _inventory(monkeypatch, rows)
    monkeypatch.setattr(review_run, "_inspect", lambda _row: (["record"], {"turns": 1}))
    monkeypatch.setattr(review_run, "build_digest", lambda _records, _cap: "d")
    calls = []
    result = review_run.run_review(
        store_dir=tmp_path / "store", budget_tokens=35, runner=_fake_runner(calls)
    )
    assert result["coverage"]["pending"] == 2
    assert all(
        row["status"] == "pending" and row["reason"] == "budget"
        for row in result["sessions"][1:]
    )
    index = read_index(tmp_path / "store")
    assert index[("codex", "b")]["status"] == "pending"
    assert index[("codex", "c")]["status"] == "pending"
    _inventory(
        monkeypatch,
        [
            _row(tmp_path / "a.jsonl", "a"),
            {**_row(tmp_path / "b.jsonl", "b"), "status": "skipped: out of window"},
            {**_row(tmp_path / "c.jsonl", "c"), "status": "skipped: out of window"},
        ],
    )
    second = review_run.run_review(
        store_dir=tmp_path / "store", budget_tokens=35, runner=_fake_runner(calls)
    )
    assert second["coverage"]["pending"] == 1
    assert second["sessions"][2]["status"] == "pending"


def test_rate_limit_returns_pending_and_is_retried(monkeypatch, tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("one\n")
    _inventory(monkeypatch, [_row(transcript)])
    monkeypatch.setattr(review_run, "_inspect", lambda _row: (["record"], {"turns": 1}))
    monkeypatch.setattr(review_run, "build_digest", lambda _records, _cap: "d")
    calls = []

    def rate_limit(_command, **kwargs):
        calls.append(kwargs["input"])
        return SimpleNamespace(returncode=429, stdout="", stderr="rate limit")

    store = tmp_path / "store"
    first = review_run.run_review(store_dir=store, runner=rate_limit)
    assert first["sessions"][0]["status"] == "pending"
    assert first["sessions"][0]["reason"] == "rate_limited"
    assert first["coverage"]["pending"] == 1
    limited = read_index(store)[("codex", "s1")]
    assert (limited["status"], limited["reason"]) == ("pending", "rate_limited")
    review_run.run_review(store_dir=store, runner=_fake_runner(calls))
    assert len(calls) >= 2


def test_no_model_does_not_write_analyzed_ledger(monkeypatch, tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("{}\n")
    _inventory(monkeypatch, [_row(transcript)])
    inspections = []
    monkeypatch.setattr(
        review_run, "_inspect", lambda _row: (inspections.append(1) or [], {"turns": 1})
    )
    store = tmp_path / "store"
    calls = []
    fake = _fake_runner(calls)
    result = review_run.run_review(no_model=True, store_dir=store, runner=fake)
    assert result["coverage"]["analyzed"] == 1
    assert not (store / "reviewed.jsonl").exists()
    assert (store / "reviews").exists()
    review_run.run_review(no_model=True, store_dir=store, runner=fake)
    assert inspections == [1, 1]
    assert calls == []


def test_no_model_does_not_import_sweep_rows_into_ledger(monkeypatch, tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("{}\n")
    _inventory(monkeypatch, [_row(transcript)])
    monkeypatch.setattr(
        "varde_learn.loop.analyzed.read_all",
        lambda _store: [{"harness": "codex", "session": "s1"}],
    )
    monkeypatch.setattr(review_run, "_inspect", lambda _row: ([], {"turns": 1}))
    store = tmp_path / "store"
    result = review_run.run_review(
        no_model=True, store_dir=store, runner=_fake_runner([])
    )
    assert result["coverage"]["analyzed"] == 1
    assert not (store / "reviewed.jsonl").exists()


def test_no_model_wires_windowed_spend_into_report_and_snapshot(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from varde_learn.loop.review.spend import read_previous

    transcript = tmp_path / "session.jsonl"
    transcript.write_text("{}\n")
    _inventory(monkeypatch, [_row(transcript)])
    record = SimpleNamespace(
        usage_record={"input_tokens": 12, "output_tokens": 2},
        usage_last=None,
        usage_total=None,
        timestamp="2026-10-22T12:00:00+00:00",
        model="test",
        provider_message_id="msg",
        transcript_id="transcript",
        tool_name=None,
        role="user",
        text_excerpt="Review branch: safe-branch",
    )
    monkeypatch.setattr(review_run, "_inspect", lambda _row: ([record], {"turns": 1}))
    store = tmp_path / "store"
    result = review_run.run_review(no_model=True, store_dir=store, window="2026-10-22")
    report = Path(result["report_path"]).read_text()
    snapshot = read_previous(store, "9999-12-31")
    assert "## Token spend" in report
    assert "Weighted" in report
    assert "Claude only" in report
    assert snapshot is not None
    assert snapshot["totals"]["weighted"] == 22
    assert snapshot["window"]["start"].startswith("2026-10-22")


def test_inspection_error_is_redacted_in_output_and_ledger(monkeypatch, tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("{}\n")
    _inventory(monkeypatch, [_row(transcript)])
    secret = "b" * 40

    def fail(_row):
        raise ValueError(f"bad transcript token={secret}")

    monkeypatch.setattr(review_run, "_inspect", fail)
    store = tmp_path / "store"
    result = review_run.run_review(store_dir=store)
    ledger_row = read_index(store)[("codex", "s1")]
    assert "bad transcript" in result["sessions"][0]["reason"]
    assert secret not in result["sessions"][0]["reason"]
    assert "bad transcript" in ledger_row["reason"]
    assert secret not in ledger_row["reason"]


def test_fingerprint_failures_retry_three_times(monkeypatch, tmp_path):
    _inventory(monkeypatch, [_row(tmp_path / "missing.jsonl")])
    store = tmp_path / "store"
    fake = _fake_runner([])
    for _ in range(3):
        review_run.run_review(store_dir=store, runner=fake)
    row = read_index(store)[("codex", "s1")]
    assert row["status"] == "skipped"
    assert row["reason"] == "too large or unreadable"
    assert row["attempts"] == 3


def test_friction_uses_evidence_project_and_review_key(monkeypatch, tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("one\n")
    row = _row(transcript)
    _inventory(monkeypatch, [row])
    monkeypatch.setattr(review_run, "_inspect", lambda _row: (["record"], {"turns": 1}))
    monkeypatch.setattr(review_run, "build_digest", lambda _records, _cap: "d")
    store = tmp_path / "store"
    result = review_run.run_review(
        store_dir=store, runner=_fake_runner([], finding=True)
    )
    from varde_learn.loop.friction_repository import open_repository

    state = open_repository(store).event_log().state
    assert result["friction_added"] == 1
    assert "review-key:" in state.occurrences[0].evidence
    assert state.occurrences[0].cwd == row["cwd"]


def test_friction_failures_are_isolated_and_use_store_for_missing_cwd(
    monkeypatch, tmp_path
):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("one\n")
    row = _row(transcript)
    row["cwd"] = str(tmp_path / "removed-worktree")
    _inventory(monkeypatch, [row])
    monkeypatch.setattr(review_run, "_inspect", lambda _row: (["record"], {"turns": 1}))
    monkeypatch.setattr(review_run, "build_digest", lambda _records, _cap: "d")
    monkeypatch.setattr(
        review_run,
        "_synthesize_observations",
        lambda *_args: (
            {
                "setup": [],
                "project": [
                    {
                        "title": title,
                        "proposal": "proposal",
                        "evidence": [{"harness": "codex", "session_id": "s1"}],
                    }
                    for title in ("First", "Second")
                ],
            },
            1,
            None,
            False,
            "ok",
            None,
        ),
    )
    monkeypatch.setattr(
        review_run,
        "friction_candidates",
        lambda findings, _keys: [
            {"title": row["title"], "evidence": "review-key:test"}
            for row in findings["project"]
        ],
    )
    requested_cwds = []

    def add_friction(_repository, request):
        requested_cwds.append(request.cwd)
        if len(requested_cwds) == 1:
            raise OSError("removed worktree")

    monkeypatch.setattr("varde_learn.loop.store.write.add_friction", add_friction)
    store = tmp_path / "store"
    result = review_run.run_review(
        store_dir=store, runner=_fake_runner([], finding=True)
    )
    assert result["friction_failed"] == 1
    assert result["friction_added"] == 1
    assert requested_cwds == [store, store]
    assert Path(result["report_path"]).exists()


def test_sweep_import_is_reanalyzed_by_model_then_replaced(monkeypatch, tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("one\n")
    _inventory(monkeypatch, [_row(transcript)])
    monkeypatch.setattr(
        "varde_learn.loop.analyzed.read_all",
        lambda _store: [{"harness": "codex", "session": "s1"}],
    )
    monkeypatch.setattr(review_run, "_inspect", lambda _row: (["record"], {"turns": 1}))
    monkeypatch.setattr(review_run, "build_digest", lambda _records, _cap: "d")
    calls = []
    store = tmp_path / "store"
    review_run.run_review(store_dir=store, runner=_fake_runner(calls))
    assert len(calls) == 2
    assert read_index(store)[("codex", "s1")]["source"] == "review"


def test_dry_run_redacts_json_and_does_not_write(monkeypatch, tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("{}\n")
    row = _row(transcript)
    row["cwd"] = "a" * 40
    secret = "token=" + "b" * 40
    _inventory(
        monkeypatch,
        [row],
        [{"root": str(tmp_path), "status": "error", "reason": secret}],
    )
    result = review_run.run_review(dry_run=True, store_dir=tmp_path / "store")
    assert result["sessions"][0]["cwd"] == "a" * 40
    assert "b" * 40 not in str(result)
    assert not (tmp_path / "store" / "review.lock").exists()


def test_structural_paths_survive_result_redaction():
    from varde_learn.loop.review.run import _redact_result_text

    path = "/" + "a" * 60
    result = _redact_result_text(
        {
            "report_path": path,
            "sessions": [{"cwd": path, "path": path, "reason": "password=hunter2"}],
        }
    )
    encoded = json.dumps(result)
    assert path in encoded
    assert result["report_path"] == path
    assert result["sessions"][0]["cwd"] == path
    assert "hunter2" not in encoded


def test_location_snapshot_does_not_duplicate_missing_root():
    from varde_learn.loop.review.run import _location_rows
    from varde_learn.loop.sources import Location

    missing = Location("codex", Path("/missing"), "config", "missing", "not found")
    rows = _location_rows(
        [missing],
        [{"root": "/missing", "status": "missing", "reason": "not found"}],
    )
    assert rows == [
        {
            "harness": "codex",
            "path": "/missing",
            "origin": "config",
            "status": "missing",
            "reason": "not found",
        }
    ]


def test_concurrent_run_fails_clearly(monkeypatch, tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    with (
        file_lock(store / "review.lock", timeout=0),
        pytest.raises(RuntimeError, match="already running"),
    ):
        review_run.run_review(store_dir=store)
