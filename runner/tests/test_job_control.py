from varde_runner.job_control import (
    review_run_fields,
    soak_run_fields,
    sweep_run_fields,
)


def test_sweep_run_fields_projects_failure_and_tokens():
    assert sweep_run_fields(
        {
            "state": "failed",
            "failures": [{"error": "one failed"}],
            "summary_error": None,
            "model_tokens": 42,
        }
    ) == {"outcome": "failed", "error": "one failed", "model_tokens": 42}


def test_soak_run_fields_projects_error_without_tokens():
    assert soak_run_fields({"state": "failed", "error": "CLI failed"}) == {
        "outcome": "failed",
        "error": "CLI failed",
        "model_tokens": None,
    }


def test_review_run_fields_projects_tokens_and_cost():
    assert review_run_fields(
        {"state": "succeeded", "model_tokens": 42, "cost_usd": 0.2}
    ) == {"outcome": "succeeded", "error": None, "model_tokens": 42, "cost_usd": 0.2}


def test_sweep_warnings_do_not_fail_run_or_become_error():
    assert sweep_run_fields(
        {"state": "succeeded", "failures": [], "warnings": ["oversized"]}
    ) == {
        "outcome": "succeeded",
        "error": None,
        "model_tokens": None,
    }


def test_sweep_summary_error_does_not_fail_run():
    assert sweep_run_fields(
        {"state": "succeeded", "summary_error": "summary unavailable"}
    ) == {"outcome": "succeeded", "error": None, "model_tokens": None}


def test_review_run_fields_discards_invalid_numeric_fields():
    assert review_run_fields(
        {"state": "succeeded", "model_tokens": True, "cost_usd": "0.2"}
    ) == {"outcome": "succeeded", "error": None, "model_tokens": None, "cost_usd": None}
