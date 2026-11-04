from __future__ import annotations

import io
import json
import os
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

from varde_data import friction_events
from varde_learn.loop import analyzed, sweep_digest
from varde_learn.loop.cli_sweep import run as run_cli
from varde_learn.loop.sweep import run as sweep

GOLDENS = Path(__file__).parent / "golden" / "ledger"
FIXTURES = Path(__file__).parents[3] / "data" / "tests" / "fixtures" / "ledger"


def _outcome(action):
    try:
        return {"value": action()}
    except Exception as error:  # noqa: BLE001 - preserve exception type and message.
        return {"exception": type(error).__name__, "message": str(error)}


def _capture(tmp_path, monkeypatch):  # noqa: PLR0915 - one end-to-end golden scenario.
    fixture = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, fixture)
    absent_ledger = tmp_path / "absent-ledger"
    analyzed_result = {
        "absent_read": analyzed.read_all(absent_ledger),
        "absent_seen": sorted(analyzed.seen(absent_ledger, "codex")),
    }
    ledger = tmp_path / "ledger-store"
    ledger.mkdir(exist_ok=True)
    shutil.copyfile(fixture / "analyzed.jsonl", ledger / "analyzed.jsonl")
    analyzed_before = (ledger / "analyzed.jsonl").read_bytes()
    rows = analyzed.read_all(ledger)
    seen = sorted(analyzed.seen(ledger, "codex"))
    analyzed.mark(ledger, "codex", "after-tail", "2026-10-24T12:00:00Z", "marked")
    analyzed_result.update(
        {
            "before": analyzed_before.decode(),
            "rows": rows,
            "seen": seen,
            "after": (ledger / "analyzed.jsonl").read_bytes().decode(),
        }
    )

    digest_fixtures = fixture / "digests"
    digest_dates = {
        "wrong_shape": "2026-10-23",
        "unreadable": "2026-10-22",
        "invalid_json": "2026-10-21",
        "missing_text": "2026-10-20",
        "non_string_text": "2026-10-19",
        "no_candidates": "2026-10-18",
    }
    for name, day in digest_dates.items():
        source = (
            digest_fixtures
            / {
                "wrong_shape": "wrong-shape.json",
                "unreadable": "unreadable.json",
                "invalid_json": "invalid.json",
                "missing_text": "no-text.json",
                "non_string_text": "non-string-text.json",
                "no_candidates": "no-candidates.json",
            }[name]
        )
        destination = digest_fixtures / f"{day}.json"
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copyfile(source, destination)
    digest_result = {
        "read": _outcome(lambda: sweep_digest.read_digest(fixture, date(2026, 10, 24))),
        "missing": sweep_digest.read_digest(fixture, date(2026, 10, 17)),
    }
    for name, day in digest_dates.items():
        digest_result[name] = _outcome(
            lambda day=day: sweep_digest.read_digest(fixture, date.fromisoformat(day))
        )
    written = sweep_digest.write_digest(
        fixture, date(2026, 10, 24), "written", [{"title": "Saved"}]
    )
    digest_result["written"] = written.read_bytes().decode()
    digest_result["written_read"] = sweep_digest.read_digest(
        fixture, date(2026, 10, 24)
    )

    home = tmp_path / "home"
    config_dir = home / ".config" / "varde" / "learn"
    config_dir.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    config_result = {
        "absent_repos": [str(path) for path in sweep.configured_repos()],
        "absent_summary": sweep_digest.summary_config(),
    }
    source = home / "source"
    source.mkdir()
    (source / "default-repo").mkdir()
    (source / "default-repo" / ".git").mkdir()
    config_result["default_repos"] = [str(path) for path in sweep.configured_repos()]
    config_result["default_repos"] = [
        path.replace(str(home), "$HOME") for path in config_result["default_repos"]
    ]
    config_result["configs"] = {}
    config_names = (
        "valid",
        "bad-repos",
        "bad-repos-item",
        "bad-summary",
        "bad-enabled",
        "bad-token-bool",
        "bad-token-zero",
        "bad-token-negative",
        "bad-token-str",
        "bad-token-float",
        "enabled-default-cap",
    )
    for name in config_names:
        config_path = config_dir / "sweep.toml"
        fixture_path = fixture / "configs" / f"{name}.toml"
        shutil.copyfile(fixture_path, config_path)
        repos = _outcome(sweep.configured_repos)
        if "value" in repos:
            repos = {
                "value": [
                    str(path).replace(str(home), "$HOME") for path in repos["value"]
                ]
            }
        config_result["configs"][name] = {
            "repos": repos,
            "summary": _outcome(sweep_digest.summary_config),
        }

    store = tmp_path / "sweep-store"
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    real_event_id = friction_events.event_id
    monkeypatch.setattr(
        friction_events,
        "event_id",
        lambda ts, kind, body, **_kwargs: real_event_id(
            ts, kind, body, pid=1, counter=0
        ),
    )
    monkeypatch.setattr(sweep, "configured_repos", lambda: [source / "default-repo"])
    session = {
        "harness": "codex",
        "session_id": "golden-session",
        "path": "/tmp/session.jsonl",  # noqa: S108 - stable synthetic session path.
        "workers": [],
    }
    monkeypatch.setattr(sweep, "_roots", dict)
    monkeypatch.setattr(sweep, "_sessions", lambda _repo, _roots: ([session], []))
    monkeypatch.setattr(
        sweep,
        "_inspect",
        lambda _session, _roots: (
            {"command_failures": {"pytest": {"calls": 2, "failures": 1}}},
            [],
        ),
    )
    monkeypatch.setattr(sweep, "summary_config", lambda: (False, 100))

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 24, 12, tzinfo=UTC)

    monkeypatch.setattr(sweep, "datetime", FixedDateTime)
    output, error = io.StringIO(), io.StringIO()
    code = run_cli(["sweep", "--json"], SimpleNamespace(stdout=output, stderr=error))
    cli_result = {
        "exit": code,
        "stdout": output.getvalue().replace(str(tmp_path), "$TMP"),
        "stderr": error.getvalue(),
        "analyzed": (store / "analyzed.jsonl").read_bytes().decode(),
        "digest": (store / "digests" / "2026-10-24.json").read_bytes().decode(),
    }
    return {
        "analyzed.json": json.dumps(
            analyzed_result, sort_keys=True, separators=(",", ":")
        ).encode()
        + b"\n",
        "digests.json": json.dumps(
            digest_result, sort_keys=True, separators=(",", ":")
        ).encode()
        + b"\n",
        "config.json": json.dumps(
            config_result, sort_keys=True, separators=(",", ":")
        ).encode()
        + b"\n",
        "sweep-cli.json": json.dumps(
            cli_result, sort_keys=True, separators=(",", ":")
        ).encode()
        + b"\n",
    }


def test_ledger_goldens(tmp_path, monkeypatch):
    actual = _capture(tmp_path, monkeypatch)
    if os.environ.get("UPDATE_LEDGER_GOLDENS") == "1":
        GOLDENS.mkdir(parents=True, exist_ok=True)
        for name, value in actual.items():
            (GOLDENS / name).write_bytes(value)
    expected = {
        path.name: path.read_bytes() for path in GOLDENS.iterdir() if path.is_file()
    }
    assert actual == expected
