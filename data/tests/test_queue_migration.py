from __future__ import annotations

import multiprocessing
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest
from varde_data.backends.sqlite.messages import SQLiteMessages
from varde_data.backends.sqlite.queue_schema import SCHEMA_VERSION, configure_store
from varde_data.errors import Conflict, Invalid
from varde_data.queue_migrate import migrate, verify
from varde_data.queue_mode_lock import barrier, operation
from varde_data.queue_paths import QUEUE_DATABASE

FIXTURE = Path(__file__).parent / "fixtures/queue_md/ux-audit-fixes-1.md"
DATABASE = QUEUE_DATABASE


def _working(tmp_path: Path) -> Path:
    root = tmp_path / "working"
    queue = root / "plans/bundle/queue.md"
    queue.parent.mkdir(parents=True)
    queue.write_text(FIXTURE.read_text())
    plan = root / "plans/bundle/plan.md"
    plan.write_text("---\nstatus: active\nstatus_at: '2026-10-26'\nowner: alec\n---\n")
    task = root / "plans/bundle/tasks/one.md"
    task.parent.mkdir()
    task.write_text("---\nstatus: todo\nstatus_at: null\n---\n")
    return root


def _writer(root: str, started: Any, finished: Any) -> None:
    started.set()
    with (
        operation(Path(root), timeout=10),
        sqlite3.connect(Path(root) / DATABASE) as db,
    ):
        db.execute(
            "INSERT INTO queue_items "
            "(id,plan_dir,findings,owned_files,state,queue_name) "
            "VALUES('late','bundle','','','queued','bundle')"
        )
    finished.set()


def test_dry_run_does_not_write_and_full_migration_verifies(tmp_path: Path) -> None:
    root = _working(tmp_path)
    result = migrate(root, dry_run=True)
    assert result.dry_run
    assert not (root / ".cache/data/queue.sqlite3").exists()
    assert not (root / ".cache/data/backups").exists()
    assert not (root / ".cache/data/queue.mode.lock").exists()
    assert not (root / ".cache").exists()

    result = migrate(root)

    assert result.backup is None
    assert result.diffs == ()
    assert result.skipped == ()
    assert verify(root) == []
    assert (root / ".cache/data/queue.version").read_text() == f"{SCHEMA_VERSION}\n"
    with sqlite3.connect(root / DATABASE) as db:
        assert db.execute(
            "SELECT value FROM queue_store_meta WHERE key='store_mode'"
        ).fetchone() == ("sqlite",)
        assert db.execute("SELECT COUNT(*) FROM queue_items").fetchone() == (6,)
        assert db.execute(
            "SELECT queue_name FROM queue_items WHERE id='A'"
        ).fetchone() == ("plans/bundle/queue.md",)
        assert db.execute("SELECT COUNT(*) FROM plan_state").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM task_state").fetchone() == (1,)


def test_crash_after_import_is_idempotent_and_mode_stays_markdown(
    tmp_path: Path,
) -> None:
    root = _working(tmp_path)

    def crash(step: str) -> None:
        if step == "imported":
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError, match="simulated crash"):
        migrate(root, crash=crash)
    with sqlite3.connect(root / DATABASE) as db:
        assert db.execute(
            "SELECT value FROM queue_store_meta WHERE key='store_mode'"
        ).fetchone() == ("markdown",)
    assert migrate(root).diffs == ()
    assert migrate(root).diffs == ()
    with sqlite3.connect(root / DATABASE) as db:
        assert db.execute("SELECT COUNT(*) FROM queue_items").fetchone() == (6,)


def test_verify_catches_tampered_row_and_prevents_flip(tmp_path: Path) -> None:
    root = _working(tmp_path)
    migrate(root)
    with sqlite3.connect(root / DATABASE) as db:
        db.execute("UPDATE queue_items SET findings='tampered' WHERE id='A'")
    assert any("findings" in diff for diff in verify(root))
    with pytest.raises(Conflict, match="verification failed"):
        migrate(root)
    with sqlite3.connect(root / DATABASE) as db:
        assert db.execute(
            "SELECT value FROM queue_store_meta WHERE key='store_mode'"
        ).fetchone() == ("sqlite",)


def test_operation_waits_for_migration_barrier_then_sees_sqlite(tmp_path: Path) -> None:
    root = _working(tmp_path)
    context = multiprocessing.get_context("spawn")
    started, finished = context.Event(), context.Event()
    process = context.Process(target=_writer, args=(str(root), started, finished))
    with barrier(root, timeout=5):
        process.start()
        assert started.wait(5)
        time.sleep(0.15)
        assert not finished.is_set()
        # The nested migration barrier is reentrant for its owning thread.
        migrate(root)
    process.join(10)
    assert process.exitcode == 0
    assert finished.is_set()
    with sqlite3.connect(root / DATABASE) as db:
        assert db.execute(
            "SELECT value FROM queue_store_meta WHERE key='store_mode'"
        ).fetchone() == ("sqlite",)
        assert db.execute("SELECT id FROM queue_items WHERE id='late'").fetchone() == (
            "late",
        )


def test_existing_store_gets_verified_backup_before_migration(tmp_path: Path) -> None:
    root = _working(tmp_path)
    database = root / DATABASE
    database.parent.mkdir(parents=True)
    SQLiteMessages(database)
    with sqlite3.connect(database) as db:
        configure_store(db)
    report = migrate(root)
    assert report.backup is not None and report.backup.is_file()


def test_line_queue_is_imported_and_verified(tmp_path: Path) -> None:
    root = _working(tmp_path)
    queue = root / "plans/bundle/notes/queue.md"
    queue.parent.mkdir()
    source = "# Queue\na-task | fix:yes | esc:1 | worktree:-\n\nNotes stay here.\n"
    queue.write_text(source)

    report = migrate(root)

    assert report.line_queues == (str(queue),)
    assert report.skipped_lines == (f"{queue}:4: Notes stay here.",)
    assert migrate(root).line_queues == (str(queue),)
    assert verify(root) == []


def test_verify_catches_tampered_queue_metadata_header(tmp_path: Path) -> None:
    root = _working(tmp_path)
    migrate(root)
    with sqlite3.connect(root / DATABASE) as db:
        db.execute(
            "UPDATE queue_meta SET header='{}' WHERE queue_name=?",
            ("plans/bundle/queue.md",),
        )

    assert any("queue metadata" in diff and "header" in diff for diff in verify(root))


def test_unknown_queue_format_is_reported_as_skipped(tmp_path: Path) -> None:
    root = _working(tmp_path)
    queue = root / "plans/bundle/unknown/queue.md"
    queue.parent.mkdir(parents=True)
    queue.write_text("This is not a queue format.\n")

    report = migrate(root)

    assert report.unknown_formats == (str(queue),)
    assert any(f"{queue}: skipped: unknown format" in value for value in report.skipped)


def test_task_markdown_without_frontmatter_is_skipped(tmp_path: Path) -> None:
    root = _working(tmp_path)
    task_document = root / "plans/bundle/tasks/README.md"
    task_document.write_text(
        "Shared brief for migration explorers.\n"
        "- Read-only: compare sources and report findings.\n"
    )

    report = migrate(root)

    assert report.skipped == (f"{task_document}: skipped: not a task state document",)
    assert verify(root) == []
    with sqlite3.connect(root / DATABASE) as db:
        assert db.execute("SELECT COUNT(*) FROM task_state").fetchone() == (1,)


def test_migration_imports_crlf_task_frontmatter(tmp_path: Path) -> None:
    root = _working(tmp_path)
    task = root / "plans/bundle/tasks/crlf-task.md"
    task.write_bytes(b"---\r\nstatus: todo\r\n---\r\nTask body.\r\n")

    report = migrate(root)

    assert report.skipped == ()
    with sqlite3.connect(root / DATABASE) as db:
        assert db.execute(
            "SELECT task_id,status FROM task_state WHERE task_id='crlf-task'"
        ).fetchone() == ("crlf-task", "todo")
    assert verify(root) == []


def test_migration_rejects_present_null_task_status(tmp_path: Path) -> None:
    root = _working(tmp_path)
    task = root / "plans/bundle/tasks/null-status.md"
    task.write_text("---\nstatus: null\n---\nTask body.\n")

    with pytest.raises(Invalid, match="task status .* must be a scalar"):
        migrate(root)
    assert not (root / ".cache/data/queue.sqlite3").exists()


def test_table_id_collision_aborts_without_changing_store(tmp_path: Path) -> None:
    root = _working(tmp_path)
    first = root / "plans/group-a/bundle/queue.md"
    second = root / "plans/group-b/bundle/queue.md"
    for path, plan_dir in ((first, "group-a"), (second, "group-b")):
        path.parent.mkdir(parents=True)
        path.write_text(
            f"# Bundle\n| id | plan dir |\n| --- | --- |\n| shared | {plan_dir} |\n"
        )
    database = root / DATABASE
    database.parent.mkdir(parents=True)
    SQLiteMessages(database)
    with sqlite3.connect(database) as db:
        configure_store(db)
        db.execute(
            "INSERT INTO queue_store_meta(key,value) VALUES('sentinel','unchanged')"
        )

    with pytest.raises(Conflict) as error:
        migrate(root)

    assert str(first) in str(error.value)
    assert str(second) in str(error.value)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM queue_items").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM queue_meta").fetchone() == (0,)
        assert db.execute(
            "SELECT value FROM queue_store_meta WHERE key='sentinel'"
        ).fetchone() == ("unchanged",)
        assert (
            db.execute(
                "SELECT value FROM queue_store_meta WHERE key='store_mode'"
            ).fetchone()
            is None
        )
