"""Small persistence operations for job schedules and run history."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_runner.job_registry import JobSpec, effective_enabled

RUN_HISTORY_LIMIT = 200
MAX_RUN_BUDGET_TOKENS = 10_000_000


def _now() -> str:
    return datetime.now(UTC).isoformat()


def open_job_store(data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(data_dir / "runner.sqlite3")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """CREATE TABLE IF NOT EXISTS job_schedules (
        job_key TEXT PRIMARY KEY, enabled INTEGER NOT NULL,
        schedule_time TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS job_runs (
        id INTEGER PRIMARY KEY, job_key TEXT NOT NULL, started_at TEXT NOT NULL,
        finished_at TEXT, trigger TEXT NOT NULL, outcome TEXT NOT NULL,
        error TEXT, model_tokens INTEGER, cost_usd REAL);
        CREATE INDEX IF NOT EXISTS job_runs_job_id_idx ON job_runs(job_key, id DESC);"""
    )
    ensure_budget_column(connection)
    connection.commit()
    return connection


def ensure_budget_column(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(job_schedules)")}
    if "run_budget_tokens" not in columns:
        connection.execute(
            "ALTER TABLE job_schedules ADD COLUMN run_budget_tokens INTEGER"
        )
        connection.commit()


def fail_stale_runs(connection: sqlite3.Connection) -> None:
    connection.execute(
        "UPDATE job_runs SET finished_at = ?, outcome = 'failed', "
        "error = COALESCE(error, 'runner restarted while job was running') "
        "WHERE outcome = 'running'",
        (_now(),),
    )
    connection.commit()


def get_enabled(connection: sqlite3.Connection, spec: JobSpec) -> bool:
    row = connection.execute(
        "SELECT enabled FROM job_schedules WHERE job_key = ?", (spec.key,)
    ).fetchone()
    return effective_enabled(spec, None if row is None else bool(row[0]))


def set_enabled(connection: sqlite3.Connection, spec: JobSpec, enabled: bool) -> None:
    connection.execute(
        """INSERT INTO job_schedules(
        job_key, enabled, schedule_time, updated_at, run_budget_tokens)
        VALUES (?, ?, ?, ?, ?) ON CONFLICT(job_key) DO UPDATE SET
        enabled = excluded.enabled, updated_at = excluded.updated_at""",
        (spec.key, int(enabled), spec.default_time, _now(), None),
    )
    connection.commit()


def get_budget(connection: sqlite3.Connection, spec: JobSpec) -> int | None:
    row = connection.execute(
        "SELECT run_budget_tokens FROM job_schedules WHERE job_key = ?", (spec.key,)
    ).fetchone()
    return spec.run_budget_tokens if row is None or row[0] is None else int(row[0])


def set_budget(connection: sqlite3.Connection, spec: JobSpec, budget: int) -> None:
    if (
        isinstance(budget, bool)
        or not isinstance(budget, int)
        or not 0 < budget <= MAX_RUN_BUDGET_TOKENS
    ):
        raise ValueError("run_budget_tokens must be a positive integer within the cap")
    connection.execute(
        """INSERT INTO job_schedules(
        job_key, enabled, schedule_time, updated_at, run_budget_tokens)
        VALUES (?, ?, ?, ?, ?) ON CONFLICT(job_key) DO UPDATE SET
        run_budget_tokens = excluded.run_budget_tokens,
        updated_at = excluded.updated_at""",
        (
            spec.key,
            int(get_enabled(connection, spec)),
            spec.default_time,
            _now(),
            budget,
        ),
    )
    connection.commit()


def start_run(connection: sqlite3.Connection, job_key: str, trigger: str) -> int:
    if trigger not in {"schedule", "manual"}:
        raise ValueError(f"invalid job trigger: {trigger}")
    cursor = connection.execute(
        "INSERT INTO job_runs(job_key, started_at, trigger, outcome) "
        "VALUES (?, ?, ?, 'running')",
        (job_key, _now(), trigger),
    )
    trim_runs(connection, job_key)
    connection.commit()
    run_id = cursor.lastrowid
    if run_id is None:
        raise RuntimeError("job run insert returned no row id")
    return run_id


def finish_run(
    connection: sqlite3.Connection,
    run_id: int,
    *,
    outcome: str,
    error: str | None = None,
    model_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    if outcome not in {"succeeded", "failed"}:
        raise ValueError(f"invalid completed job outcome: {outcome}")
    connection.execute(
        """UPDATE job_runs SET finished_at = ?, outcome = ?, error = ?,
        model_tokens = ?, cost_usd = ? WHERE id = ?""",
        (_now(), outcome, error, model_tokens, cost_usd, run_id),
    )
    connection.commit()


def recent_runs(
    connection: sqlite3.Connection, job_key: str, limit: int = 20
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT id, job_key, started_at, finished_at, trigger, outcome, error, "
        "model_tokens, cost_usd FROM job_runs WHERE job_key = ? "
        "ORDER BY id DESC LIMIT ?",
        (job_key, max(0, min(limit, RUN_HISTORY_LIMIT))),
    )
    return [dict(row) for row in rows]


def trim_runs(connection: sqlite3.Connection, job_key: str) -> None:
    connection.execute(
        """DELETE FROM job_runs WHERE job_key = ? AND id NOT IN
        (SELECT id FROM job_runs WHERE job_key = ? ORDER BY id DESC LIMIT ?)""",
        (job_key, job_key, RUN_HISTORY_LIMIT),
    )
