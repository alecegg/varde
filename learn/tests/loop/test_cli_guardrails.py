from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta

from varde_learn.loop import cli_guardrails


class _Io:
    def __init__(self):
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


def test_guardrails_lists_counts_in_json(monkeypatch):
    output = _Io()
    monkeypatch.setattr(
        cli_guardrails.guardrails,
        "load_registry",
        lambda: [{"id": "g", "kind": "cli-check", "owner": "x", "purpose": "p"}],
    )
    monkeypatch.setattr(
        cli_guardrails.calls,
        "read_calls_strict",
        lambda: [
            {
                "ts": "2026-10-22T10:00:00+00:00",
                "command": "x",
                "status": "success",
                "duration_s": 0,
                "session": None,
                "guardrail": "g",
            }
        ],
    )
    assert cli_guardrails.run(["guardrails", "--json"], output) == 0
    payload = json.loads(output.stdout.getvalue())
    assert payload["data"]["guardrails"][0]["fired"] == 1
    assert payload["data"]["guardrails"][0]["blocked"] == 0


def test_guardrails_json_preserves_store_config_error(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.toml").write_text('[default]\nlearn = "  "\n')
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.delenv("VARDE_LEARN_STORE", raising=False)
    output = _Io()

    assert cli_guardrails.run(["guardrails", "--json"], output) == 2

    error = json.loads(output.stderr.getvalue())["data"]["error"]
    assert error["code"] == "store_config_error"
    assert error["message"] == (
        f"invalid global learn store configuration at {config / 'config.toml'}: "
        "`default.learn` must be a non-empty path string"
    )


def test_guardrails_fire_appends_explicit_row(monkeypatch):
    output = _Io()
    recorded = []
    monkeypatch.setattr(
        cli_guardrails.guardrails,
        "load_registry",
        lambda: [{"id": "g", "kind": "hook", "owner": "x", "purpose": "p"}],
    )
    monkeypatch.setattr(
        cli_guardrails.calls, "append_call", lambda row: recorded.append(row) or True
    )
    assert cli_guardrails.run(["guardrails", "fire", "g", "--blocked"], output) == 0
    assert recorded[0]["guardrail"] == "g"
    assert recorded[0]["status"] == "blocked"


def test_guardrails_dead_filters_to_zero_firings(monkeypatch):
    output = _Io()
    monkeypatch.setattr(
        cli_guardrails.guardrails,
        "load_registry",
        lambda: [{"id": "g", "kind": "hook", "owner": "x", "purpose": "p"}],
    )
    monkeypatch.setattr(cli_guardrails.calls, "read_calls_strict", list)
    assert cli_guardrails.run(["guardrails", "--dead"], output) == 0
    assert "g [hook] 0 fired, 0 blocked" in output.stdout.getvalue()


def test_fire_store_failure_is_best_effort(monkeypatch):
    output = _Io()
    monkeypatch.setattr(
        cli_guardrails.guardrails,
        "load_registry",
        lambda: [{"id": "g", "kind": "hook", "owner": "x", "purpose": "p"}],
    )
    monkeypatch.setattr(cli_guardrails.calls, "append_call", lambda row: False)
    assert cli_guardrails.run(["guardrails", "fire", "g"], output) == 0
    assert "warning:" in output.stderr.getvalue()


def test_guardrails_window_filters_counts_and_dead_list(monkeypatch):
    now = datetime.now(UTC)
    entries = [
        {"id": "live", "kind": "hook", "owner": "x", "purpose": "p"},
        {"id": "dead", "kind": "hook", "owner": "x", "purpose": "p"},
    ]
    monkeypatch.setattr(cli_guardrails.guardrails, "load_registry", lambda: entries)
    monkeypatch.setattr(
        cli_guardrails.calls,
        "read_calls_strict",
        lambda: [
            {
                "ts": (now - timedelta(days=31)).isoformat(),
                "command": "x",
                "status": "success",
                "duration_s": 0,
                "session": None,
                "guardrail": "live",
            },
            {
                "ts": now.isoformat(),
                "command": "x",
                "status": "success",
                "duration_s": 0,
                "session": None,
                "guardrail": "live",
            },
        ],
    )
    output = _Io()
    assert cli_guardrails.run(["guardrails", "--window", "30d", "--json"], output) == 0
    data = json.loads(output.stdout.getvalue())["data"]["guardrails"]
    assert [(row["id"], row["fired"]) for row in data] == [("live", 1), ("dead", 0)]
    dead_output = _Io()
    assert (
        cli_guardrails.run(["guardrails", "--window", "30d", "--dead"], dead_output)
        == 0
    )
    assert "dead [hook]" in dead_output.stdout.getvalue()
    assert "live [hook]" not in dead_output.stdout.getvalue()


def test_fire_unknown_id_is_usage_error_json(monkeypatch):
    monkeypatch.setattr(cli_guardrails.guardrails, "load_registry", list)
    output = _Io()
    assert cli_guardrails.run(["guardrails", "fire", "missing", "--json"], output) == 2
    assert (
        json.loads(output.stderr.getvalue())["data"]["error"]["code"] == "usage_error"
    )


def test_fire_help_after_id_is_reported():
    output = _Io()
    assert cli_guardrails.run(["guardrails", "fire", "g", "--help"], output) == 0
    assert "Usage: varde learn sessions fire" in output.stdout.getvalue()
