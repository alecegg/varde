from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_data.queue import open_queue, open_slots
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItemInput
from varde_workflow.commands import plan_queue_roles
from varde_workflow.role_queue_budget import (
    DEFAULT_LIMITS,
    BudgetLimits,
    load_limits,
    runner_toml_path,
)

VALID = (
    "[queue_budget]\n"
    "provider_max = { alpha = 0.8 }\n"
    "rss_mb_max = 4096\n"
    "cpu_pct_max = 90\n"
    "processes_max = 500\n"
    "global_worker_ceiling = 12\n"
)
REQUIRED_KEYS = ("rss_mb_max", "cpu_pct_max", "processes_max", "global_worker_ceiling")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _omit(text: str, key: str) -> str:
    lines = [line for line in text.splitlines() if not line.startswith(key)]
    return "\n".join(lines) + "\n"


def _database(working: Path) -> Path:
    initialize(working)
    database = working / QUEUE_DATABASE
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'"
        )
    return database


def _fresh_snapshot(working: Path) -> None:
    path = working / ".cache" / "data" / "resources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "taken_at": datetime.now(UTC).isoformat(),
                "providers": {},
                "rss_mb": 1,
                "cpu_pct": 1,
                "processes": 1,
                "live_workers": 0,
            }
        ),
        encoding="utf-8",
    )


def _pull(working: Path) -> dict:
    return plan_queue_roles._run(
        SimpleNamespace(
            queue_action="pull",
            queue="roles/global",
            role="builder",
            slot="slot-1",
            epoch=1,
        ),
        working,
    )


def test_valid_table_gives_limits(tmp_path: Path) -> None:
    limits, reason = load_limits(_write(tmp_path / "runner.toml", VALID))
    assert reason == ""
    assert limits == BudgetLimits(
        provider_max={"alpha": 0.8},
        rss_mb_max=4096.0,
        cpu_pct_max=90.0,
        processes_max=500,
        global_worker_ceiling=12,
    )


def test_provider_max_is_optional(tmp_path: Path) -> None:
    text = _omit(VALID, "provider_max")
    limits, reason = load_limits(_write(tmp_path / "runner.toml", text))
    assert reason == ""
    assert limits is not None
    assert limits.provider_max == {}


def test_missing_file_uses_default_limits(tmp_path: Path) -> None:
    assert load_limits(tmp_path / "runner.toml") == (DEFAULT_LIMITS, "")


def test_file_without_table_uses_default_limits(tmp_path: Path) -> None:
    path = _write(tmp_path / "runner.toml", "[runner]\nport = 4000\n")
    assert load_limits(path) == (DEFAULT_LIMITS, "")


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_missing_key_is_invalid(tmp_path: Path, key: str) -> None:
    limits, reason = load_limits(_write(tmp_path / "runner.toml", _omit(VALID, key)))
    assert limits is None
    assert f"queue_budget.{key}" in reason


def test_non_table_section_is_invalid(tmp_path: Path) -> None:
    limits, reason = load_limits(_write(tmp_path / "runner.toml", "queue_budget = 5\n"))
    assert limits is None
    assert "queue_budget" in reason


def test_wrong_type_names_the_key(tmp_path: Path) -> None:
    text = VALID.replace("processes_max = 500", 'processes_max = "many"')
    limits, reason = load_limits(_write(tmp_path / "runner.toml", text))
    assert limits is None
    assert "queue_budget.processes_max" in reason


def test_unparsable_file_is_invalid(tmp_path: Path) -> None:
    limits, reason = load_limits(_write(tmp_path / "runner.toml", "[queue_budget\n"))
    assert limits is None
    assert "not valid TOML" in reason


def test_runner_toml_path_follows_runner_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path / "conf"))
    assert runner_toml_path() == tmp_path / "conf" / "runner.toml"

    monkeypatch.delenv("VARDE_RUNNER_CONFIG_DIR")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert runner_toml_path() == tmp_path / ".config" / "varde" / "runner.toml"


def test_pull_with_invalid_config_claims_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_snapshot(tmp_path)
    _database(tmp_path)
    queue = open_queue(tmp_path)
    queue.enqueue(
        QueueItemInput("item-1", "plan", role="builder", queue_name="roles/global")
    )
    _write(tmp_path / "conf" / "runner.toml", _omit(VALID, "global_worker_ceiling"))
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path / "conf"))

    result = _pull(tmp_path)

    assert result["item"] is None
    assert "queue_budget.global_worker_ceiling" in result["reason"]
    assert queue.get("roles/global", "item-1").state == "queued"


def test_status_reports_invalid_config_and_no_ready_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_snapshot(tmp_path)
    _database(tmp_path)
    queue = open_queue(tmp_path)
    queue.enqueue(
        QueueItemInput("item-1", "plan", role="builder", queue_name="roles/global")
    )
    _write(tmp_path / "conf" / "runner.toml", _omit(VALID, "rss_mb_max"))
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path / "conf"))

    status = plan_queue_roles._run(
        SimpleNamespace(queue_action="status", queue="roles/global"), tmp_path
    )

    assert status["budget"]["ok"] is False
    assert "queue_budget.rss_mb_max" in status["budget"]["reason"]
    assert status["roles"]["builder"]["ready"] == 0


def test_config_toml_is_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "work"
    _fresh_snapshot(working)
    _database(working)
    queue = open_queue(working)
    queue.enqueue(
        QueueItemInput("item-1", "plan", role="builder", queue_name="roles/global")
    )
    open_slots(working).register(
        "slot-1", plan_id="plan", role="builder", agent_ref="agent-1", lease_s=60
    )
    _write(
        tmp_path / "config" / "config.toml",
        "[queue_budget]\nrss_mb_max = 0\ncpu_pct_max = 0\n"
        "processes_max = 0\nglobal_worker_ceiling = 0\n",
    )
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path / "conf"))

    result = _pull(working)

    assert result["item"]["id"] == "item-1"
    assert result["reason"] == "claimed"
