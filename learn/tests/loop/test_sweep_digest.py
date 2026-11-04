from varde_learn.loop import sweep_digest
from varde_learn.loop.sweep import run


def test_rank_candidates_orders_estimated_savings():
    findings = [
        {"title": "tokens", "estimated_tokens_saved": 500},
        {"title": "time", "estimated_seconds_saved": 120},
        {"title": "small", "estimated_seconds_saved": 30},
    ]
    assert [item["title"] for item in sweep_digest.rank_candidates(findings)] == [
        "time",
        "small",
        "tokens",
    ]
    assert sweep_digest.render_digest([]) == "No improvement candidates found."


def test_summary_flag_off_skips_claude(monkeypatch):
    monkeypatch.setattr(sweep_digest.shutil, "which", lambda _: None)
    assert sweep_digest.summarize_with_claude("digest", token_cap=100) == (None, None)


def test_summary_cap_prevents_call_and_limits_output(monkeypatch):
    calls = []
    monkeypatch.setattr(sweep_digest.shutil, "which", lambda _: "/bin/claude")

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))

        class Result:
            returncode = 0
            stdout = '{"result":"short summary","usage":{"output_tokens":8}}'

        return Result()

    monkeypatch.setattr(sweep_digest.subprocess, "run", fake_run)
    assert sweep_digest.summarize_with_claude("x", token_cap=20, input_tokens=20) == (
        None,
        None,
    )
    summary, measured = sweep_digest.summarize_with_claude(
        "x", token_cap=20, input_tokens=10
    )
    assert (summary, measured) == ("short summary", 18)
    assert calls[0][0][calls[0][0].index("--model") + 1] == "haiku"
    assert calls[0][1]["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "10"


def test_run_result_records_model_tokens(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    session = {"harness": "codex", "session_id": "one", "workers": []}
    finding = {"title": "Test", "estimated_seconds_saved": 1}
    monkeypatch.setattr(run, "configured_repos", lambda: [repo])
    monkeypatch.setattr(run, "_roots", dict)
    monkeypatch.setattr(run, "resolve_store_dir", lambda: tmp_path)
    monkeypatch.setattr(run.analyzed, "read_all", lambda _: [])
    monkeypatch.setattr(run, "_open_items", lambda _: [])
    monkeypatch.setattr(run, "_sessions", lambda *_: ([session], []))
    monkeypatch.setattr(run, "_record_candidate", lambda *_: ([finding], 0))
    monkeypatch.setattr(run, "summary_config", lambda: (True, 100))
    monkeypatch.setattr(
        run, "summarize_with_claude", lambda *args, **kwargs: ("summary", 21)
    )
    result = run.run_sweep()
    assert result["model_tokens"] == 21
    assert result["digest"]["text"] == "summary"
    assert (tmp_path / "digests" / f"{result['run_at'][:10]}.json").exists()


def test_run_with_summary_flag_off_skips_model(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    session = {"harness": "codex", "session_id": "one", "workers": []}
    finding = {"title": "Test", "estimated_seconds_saved": 1}
    monkeypatch.setattr(run, "configured_repos", lambda: [repo])
    monkeypatch.setattr(run, "_roots", dict)
    monkeypatch.setattr(run, "resolve_store_dir", lambda: tmp_path)
    monkeypatch.setattr(run.analyzed, "read_all", lambda _: [])
    monkeypatch.setattr(run, "_open_items", lambda _: [])
    monkeypatch.setattr(run, "_sessions", lambda *_: ([session], []))
    monkeypatch.setattr(run, "_record_candidate", lambda *_: ([finding], 0))
    monkeypatch.setattr(run, "summary_config", lambda: (False, 100))
    monkeypatch.setattr(
        run,
        "summarize_with_claude",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must skip")),
    )
    result = run.run_sweep()
    assert result["model_tokens"] is None
    assert result["digest"]["text"].startswith("1. Test")
