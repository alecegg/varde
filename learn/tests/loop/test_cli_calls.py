from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from varde_learn.loop import cli_calls
from varde_learn.loop.calls import FAILURE, SUCCESS


class _Io:
    def __init__(self):
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


def test_calls_json_reports_ranked_calls(monkeypatch):
    output = _Io()
    monkeypatch.setattr(
        cli_calls,
        "read_calls_strict",
        lambda: [
            {
                "ts": "2026-10-22T10:00:00+00:00",
                "command": "x",
                "status": FAILURE,
                "duration_s": 1,
                "session": "s",
            },
            {
                "ts": "2026-10-22T10:00:10+00:00",
                "command": "x",
                "status": SUCCESS,
                "duration_s": 1,
                "session": "s",
            },
        ],
    )
    assert cli_calls.run(["calls", "--json"], output) == 0
    data = json.loads(output.stdout.getvalue())
    assert data["data"]["commands"][0]["retry_rate"] == 0.5


def test_calls_help_is_reported():
    output = _Io()
    assert cli_calls.run(["calls", "--help"], output) == 0
    assert "Usage: varde learn calls" in output.stdout.getvalue()


def test_calls_help_can_follow_options():
    output = _Io()
    assert cli_calls.run(["calls", "--json", "--help"], output) == 0
    assert "Usage: varde learn calls" in output.stdout.getvalue()


def test_calls_window_requires_value():
    output = _Io()
    assert cli_calls.run(["calls", "--window"], output) == 2
    assert "requires a duration" in output.stderr.getvalue()


def test_learn_module_dispatch_uses_real_call_store(tmp_path, monkeypatch):
    from varde_learn.loop.calls import CALLS_NAME
    from varde_learn.module import _LearnModule

    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path))
    Path(tmp_path, CALLS_NAME).write_text(
        '{"ts":"2026-10-22T10:00:00Z","command":"x","status":"success","duration_s":0,"session":null}\n',
        encoding="utf-8",
    )
    output = _Io()
    assert _LearnModule().run(["sessions", "calls", "--json"], output) == 0
    assert json.loads(output.stdout.getvalue())["data"]["commands"][0]["calls"] == 1


def test_calls_window_filters_before_ranking(monkeypatch):
    now = datetime.now(UTC)
    rows = [
        {
            "ts": (now - timedelta(days=31)).isoformat(),
            "command": "old",
            "status": SUCCESS,
            "duration_s": 0,
            "session": None,
        },
        {
            "ts": now.isoformat(),
            "command": "recent",
            "status": FAILURE,
            "duration_s": 0,
            "session": None,
        },
    ]
    monkeypatch.setattr(cli_calls, "read_calls_strict", lambda: rows)
    output = _Io()
    assert cli_calls.run(["calls", "--window", "30d"], output) == 0
    assert "recent: 1 calls" in output.stdout.getvalue()
    assert "old:" not in output.stdout.getvalue()


def test_calls_empty_and_usage_error_json(monkeypatch):
    monkeypatch.setattr(cli_calls, "read_calls_strict", list)
    output = _Io()
    assert cli_calls.run(["calls"], output) == 0
    assert "No calls recorded." in output.stdout.getvalue()
    error = _Io()
    assert cli_calls.run(["calls", "--json", "--bad"], error) == 2
    assert json.loads(error.stderr.getvalue())["data"]["error"]["code"] == "usage_error"


def test_calls_json_preserves_store_config_error(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.toml").write_text('[default]\nlearn = "  "\n')
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.delenv("VARDE_LEARN_STORE", raising=False)
    output = _Io()

    assert cli_calls.run(["calls", "--json"], output) == 2

    error = json.loads(output.stderr.getvalue())["data"]["error"]
    assert error["code"] == "store_config_error"
    assert error["message"] == (
        f"invalid global learn store configuration at {config / 'config.toml'}: "
        "`default.learn` must be a non-empty path string"
    )


def test_sessions_calls_adds_guardrails_and_old_command_is_gone(
    tmp_path, monkeypatch, capsys
):
    from varde_learn.module import _LearnModule

    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path))
    output = _Io()
    assert _LearnModule().run(["sessions", "calls", "--json"], output) == 0
    assert "guardrails" in json.loads(output.stdout.getvalue())["data"]
    for old in (
        ["calls"],
        ["diagnose", "list"],
        ["guardrails"],
        ["how-report"],
        ["adopt", "recurrence"],
    ):
        assert _LearnModule().run(old, _Io()) == 2
