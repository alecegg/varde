import json
from io import StringIO
from types import SimpleNamespace

from varde_learn.loop.cli_run import run


def test_run_help_documents_all_options():
    io = SimpleNamespace(stdout=StringIO(), stderr=StringIO())
    assert run(["run", "--help"], io) == 0
    text = io.stdout.getvalue()
    for flag in ("--window", "--budget-tokens", "--no-model", "--dry-run", "--json"):
        assert flag in text


def test_run_rejects_invalid_budget():
    io = SimpleNamespace(stdout=StringIO(), stderr=StringIO())
    assert run(["run", "--budget-tokens", "0"], io) == 2
    assert "must be positive" in io.stderr.getvalue()


def test_plain_run_error_is_redacted(monkeypatch):
    io = SimpleNamespace(stdout=StringIO(), stderr=StringIO())
    monkeypatch.setattr(
        "varde_learn.loop.review.run.run_review",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("password=hunter2")),
    )
    assert run(["run"], io) == 2
    assert "hunter2" not in io.stderr.getvalue()


def test_json_errors_use_an_error_envelope_and_budget_message():
    io = SimpleNamespace(stdout=StringIO(), stderr=StringIO())
    assert run(["run", "--json", "--budget-tokens", "bad"], io) == 2
    result = json.loads(io.stdout.getvalue())
    assert result["ok"] is False
    assert (
        result["data"]["error"]["message"]
        == "--budget-tokens must be a positive integer"
    )
