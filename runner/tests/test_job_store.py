import sqlite3

from varde_runner.job_registry import JobSpec
from varde_runner.job_store import (
    fail_stale_runs,
    finish_run,
    get_budget,
    get_enabled,
    open_job_store,
    recent_runs,
    set_budget,
    set_enabled,
    start_run,
)
from varde_runner.store import SessionStore


def test_schema_adds_job_tables_without_version_bump(tmp_path):
    store = SessionStore(tmp_path)
    tables = {
        row[0]
        for row in store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"job_schedules", "job_runs"} <= tables
    assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 7
    store.connection.close()


def test_enabled_defaults_and_persists_schedule():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        "CREATE TABLE job_schedules(job_key TEXT PRIMARY KEY, "
        "enabled INTEGER NOT NULL, run_budget_tokens INTEGER, "
        "schedule_time TEXT NOT NULL, updated_at TEXT NOT NULL);"
    )
    spec = JobSpec("daily", "Daily", False, True, "03:00")
    assert get_enabled(connection, spec)
    set_enabled(connection, spec, False)
    assert not get_enabled(connection, spec)
    assert get_budget(connection, spec) is None
    new_default = JobSpec("daily", "Daily", False, True, "03:00", run_budget_tokens=64)
    assert get_budget(connection, new_default) == 64
    connection.close()


def test_run_history_finishes_and_trims_to_200():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE job_runs(id INTEGER PRIMARY KEY, job_key TEXT NOT NULL,
        started_at TEXT NOT NULL, finished_at TEXT, trigger TEXT NOT NULL,
        outcome TEXT NOT NULL, error TEXT, model_tokens INTEGER, cost_usd REAL)"""
    )
    first_id = start_run(connection, "daily", "manual")
    finish_run(connection, first_id, outcome="failed", error="broken", cost_usd=0.2)
    assert recent_runs(connection, "daily")[0]["error"] == "broken"
    for _ in range(205):
        start_run(connection, "daily", "schedule")
    assert len(recent_runs(connection, "daily", 500)) == 200
    assert connection.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0] == 200
    connection.close()


def test_open_job_store_marks_stale_runs_failed(tmp_path):
    connection = open_job_store(tmp_path)
    run_id = start_run(connection, "daily", "schedule")
    connection.close()

    reopened = open_job_store(tmp_path)
    fail_stale_runs(reopened)
    run = recent_runs(reopened, "daily")[0]
    assert run["id"] == run_id
    assert run["outcome"] == "failed"
    assert run["finished_at"] is not None
    assert "restarted" in run["error"]
    reopened.close()


def test_old_job_schedule_schema_migrates_budget_and_upserts_preserve_fields(tmp_path):
    database = tmp_path / "runner.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        "CREATE TABLE job_schedules(job_key TEXT PRIMARY KEY, "
        "enabled INTEGER NOT NULL, "
        "schedule_time TEXT NOT NULL, updated_at TEXT NOT NULL);"
    )
    connection.execute(
        "INSERT INTO job_schedules(job_key, enabled, schedule_time, updated_at) "
        "VALUES ('old-job', 1, '02:00', '2026-10-01T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()

    migrated = open_job_store(tmp_path)
    spec = JobSpec("review", "Review", True, False, "04:00", run_budget_tokens=50_000)
    assert "run_budget_tokens" in {
        row[1] for row in migrated.execute("PRAGMA table_info(job_schedules)")
    }
    assert tuple(
        migrated.execute(
            "SELECT enabled, schedule_time, updated_at, run_budget_tokens "
            "FROM job_schedules WHERE job_key = 'old-job'"
        ).fetchone()
    ) == (1, "02:00", "2026-10-01T00:00:00+00:00", None)
    assert get_budget(migrated, spec) == 50_000
    set_budget(migrated, spec, 25_000)
    set_enabled(migrated, spec, True)
    assert get_budget(migrated, spec) == 25_000
    assert get_enabled(migrated, spec)
    set_enabled(migrated, spec, False)
    assert get_budget(migrated, spec) == 25_000
    migrated.close()
