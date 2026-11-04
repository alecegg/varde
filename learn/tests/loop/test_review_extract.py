import json
import subprocess
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from varde_learn.loop.review.extract import (
    Budget,
    extract_batch,
    extract_with_claude,
    mark_review_row,
    redact_ledger_row,
    review_config,
)
from varde_learn.loop.review.ledger import read_all
from varde_learn.loop.review.synthesis import cap_synthesis_context, synthesize


def fake_runner(response, *, returncode=0, stderr=""):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            stdout=json.dumps(response), stderr=stderr, returncode=returncode
        )

    return run, calls


def test_budget_reserves_synthesis_and_stops_when_spent():
    budget = Budget(100)
    assert budget.remaining == 100
    assert budget.can_afford(79)
    assert not budget.can_afford(81)
    budget.charge(81)
    assert budget.remaining == 19
    assert not budget.can_afford(1)


def test_extraction_uses_required_cli_argv_and_accounts_cache_tokens():
    run, calls = fake_runner(
        {
            "result": "observation",
            "usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 2,
                "cache_read_input_tokens": 3,
                "output_tokens": 4,
            },
            "total_cost_usd": 0.001,
        }
    )
    budget = Budget(1000)
    result = extract_with_claude("session text", budget=budget, runner=run)
    argv, kwargs = calls[0]
    assert argv == [
        "claude",
        "-p",
        "--model",
        "haiku",
        "--no-session-persistence",
        "--tools",
        "",
        "--output-format",
        "json",
    ]
    assert kwargs["input"].startswith("varde-daily-review:")
    assert result.tokens == 19
    assert budget.used_tokens == 19
    assert result.cost_usd == 0.001


def test_rate_limit_keeps_run_pending():
    run, calls = fake_runner(
        {"result": "", "is_error": True, "subtype": "rate_limit"},
        returncode=1,
        stderr="429",
    )
    result = extract_with_claude("input", budget=Budget(1000), runner=run)
    assert result.status == "rate_limited"
    assert result.error == "rate_limit"
    assert len(calls) == 1


def test_generic_client_error_is_failed_with_redacted_reason():
    run, _ = fake_runner(
        {"result": "", "is_error": True, "error": {"message": "password=hunter2"}}
    )
    batch = extract_batch(["first", "second"], budget=Budget(1000), runner=run)
    assert batch.stop_reason == "failed"
    assert batch.stop_error is not None
    assert "hunter2" not in batch.stop_error
    assert batch.results[0].status == "failed"
    assert len(batch.results) == 1


def test_successful_model_result_mentioning_429_is_not_rate_limited():
    run, _ = fake_runner(
        {"result": "The server returned HTTP 429 in the example.", "usage": {}}
    )
    result = extract_with_claude("input", budget=Budget(1000), runner=run)
    assert result.status == "ok"
    assert "429" in (result.text or "")


def test_model_output_secret_is_redacted_after_json_envelope_parsing():
    secret = "0123456789abcdef" * 4
    run, _ = fake_runner(
        {"result": f"The observed key was {secret}", "usage": {"output_tokens": 10}}
    )
    result = extract_with_claude("input", budget=Budget(1000), runner=run)
    assert result.status == "ok"
    assert secret not in (result.text or "")


def test_budget_stop_returns_current_and_remaining_prompts_as_pending():
    runs = iter(
        [
            SimpleNamespace(
                stdout=json.dumps(
                    {
                        "result": "done",
                        "usage": {"input_tokens": 10, "output_tokens": 70},
                    }
                ),
                stderr="",
                returncode=0,
            )
        ]
    )
    batch = extract_batch(
        ["first", "second", "third"],
        budget=Budget(100),
        runner=lambda *args, **kwargs: next(runs),
    )
    assert [result.status for result in batch.results] == ["ok"]
    assert batch.stop_reason == "budget_exhausted"
    assert batch.stop_reason == "budget_exhausted"


def test_rate_limit_batch_keeps_current_session_and_rest_pending():
    run, _ = fake_runner(
        {
            "result": "",
            "is_error": True,
            "subtype": "usage_limit",
            "error": "usage limit reached",
        },
        returncode=1,
    )
    batch = extract_batch(["current", "later"], budget=Budget(1000), runner=run)
    assert batch.stop_reason == "rate_limited"
    assert batch.stop_reason == "rate_limited"
    assert batch.results == []


def test_structured_api_429_status_stops_without_result_text_match():
    run, _ = fake_runner(
        {
            "result": "normal response",
            "error": {"status": 429, "message": "request limited"},
        },
        returncode=1,
    )
    result = extract_with_claude("input", budget=Budget(1000), runner=run)
    assert result.status == "rate_limited"
    assert result.error == "{'status': 429, 'message': 'request limited'}"


def test_invalid_empty_and_timeout_results_are_failed_with_reasons():
    invalid_budget = Budget(1000)
    invalid = extract_with_claude(
        "input",
        budget=invalid_budget,
        runner=lambda *args, **kwargs: SimpleNamespace(
            stdout="not JSON", stderr="", returncode=0
        ),
    )
    empty_run, _ = fake_runner({"result": "", "usage": {}})
    empty = extract_with_claude("input", budget=Budget(1000), runner=empty_run)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("claude", 1)

    timed_out = extract_with_claude("input", budget=Budget(1000), runner=timeout)
    assert (invalid.status, invalid.error) == ("failed", "invalid client JSON")
    assert invalid.tokens > 0
    assert invalid_budget.used_tokens == invalid.tokens
    assert (empty.status, empty.error) == ("failed", "empty client result")
    assert (timed_out.status, timed_out.error) == ("failed", "Claude CLI timed out")


def test_wall_clock_budget_stops_before_runner_call():
    calls = []
    budget = Budget(1000, wall_clock_seconds=1, started_at=0, clock=lambda: 2)
    result = extract_with_claude(
        "input", budget=budget, runner=lambda *args, **kwargs: calls.append(args)
    )
    assert result.status == "budget_exhausted"
    assert calls == []


def test_review_config_reads_model_and_limits(tmp_path):
    config = tmp_path / "review.toml"
    config.write_text(
        '[review]\nmodel_id = "haiku-custom"\ntoken_budget = 500\n'
        "wall_clock_seconds = 90\nsynthesis_input_cap = 100\n"
    )
    assert review_config(config) == {
        "model_id": "haiku-custom",
        "token_budget": 500,
        "wall_clock_seconds": 90,
        "synthesis_input_cap": 100,
    }


def test_synthesis_splits_setup_and_project_findings():
    run, _ = fake_runner(
        {
            "result": json.dumps(
                {
                    "findings": {
                        "setup": [
                            {
                                "title": "Setup",
                                "evidence": [
                                    {
                                        "harness": "codex",
                                        "session_id": "s1",
                                        "anchor": 2,
                                    }
                                ],
                                "proposal": "Improve setup",
                            }
                        ],
                        "project": [
                            {
                                "title": "Project",
                                "evidence": [],
                                "proposal": "Fix project",
                            }
                        ],
                    }
                }
            ),
            "usage": {"input_tokens": 20, "output_tokens": 10},
        }
    )
    findings, result = synthesize([], [], budget=Budget(2000), runner=run)
    assert result.status == "ok"
    assert [item["title"] for item in findings["setup"]] == ["Setup"]
    assert [item["title"] for item in findings["project"]] == ["Project"]


def test_synthesis_parses_json_before_redacting_secret_values():
    secret = "0123456789abcdef" * 4
    run, _ = fake_runner(
        {
            "result": json.dumps(
                {
                    "findings": {
                        "setup": [
                            {
                                "title": f"credential {secret}",
                                "proposal": "rotate it",
                                "evidence": [],
                            }
                        ],
                        "project": [],
                    }
                }
            ),
            "usage": {"input_tokens": 20, "output_tokens": 10},
        }
    )
    findings, result = synthesize([], [], budget=Budget(2000), runner=run)
    assert result.status == "ok"
    assert secret not in (result.text or "")
    assert secret not in str(findings)


def test_synthesis_input_cap_keeps_whole_records_and_counts_instructions():
    records: list[Mapping[str, Any]] = [
        {"id": "first", "text": "short"},
        {"id": "second", "text": "ordinary words " * 100},
    ]
    included, _ = cap_synthesis_context(records, [], input_cap=80)
    assert included == [records[0]]


def test_redacts_ledger_sinks(tmp_path):
    secret = "0123456789abcdef" * 4
    safe = redact_ledger_row(
        {
            "reason": f"token={secret}",
            "last_error": f"Bearer {secret}",
            "excerpt": f"api_key={secret}",
        }
    )
    assert secret not in str(safe)
    marked = mark_review_row(
        tmp_path,
        {
            "harness": "claude",
            "session_id": "s1",
            "status": "failed",
            "reason": f"token={secret}",
            "last_error": f"Bearer {secret}",
            "excerpt": f"api_key={secret}",
        },
        latest_by_key={},
    )
    assert secret not in str(marked)
    assert secret not in str(read_all(tmp_path))
