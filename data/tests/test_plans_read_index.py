from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest
from varde_data.backends.files import plans as files_plans_module
from varde_data.backends.sqlite import plans_index as plans_index_module
from varde_data.backends.sqlite.plans_index import SqlitePlansIndex
from varde_data.errors import Invalid


def _plan(directory: Path, identifier: str = "demo") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "plan.md"
    path.write_text(
        f"---\nid: {identifier}\ntype: plan\nstatus: active\n---\n\n"
        "## Problem\nA purpose.\n\n## Open questions\n- One question\n",
        encoding="utf-8",
    )
    return path


def test_build_and_noop_refresh(tmp_path: Path) -> None:
    plan = _plan(tmp_path / "plans" / "demo")
    _backdate(plan)
    index = SqlitePlansIndex(tmp_path)
    generation = index.refresh()
    assert generation > 0
    assert index.refresh() == generation
    with sqlite3.connect(index.path) as db:
        assert db.execute("SELECT id,purpose,open_questions FROM plans").fetchone() == (
            "demo",
            "A purpose.",
            "- One question",
        )
    plan.write_text(
        plan.read_text().replace("A purpose.", "Changed."), encoding="utf-8"
    )
    assert index.refresh() == generation + 1
    plan.unlink()
    assert index.refresh() == generation + 2


def test_status_rows_reuses_generation_and_refreshes_after_change(
    tmp_path: Path, monkeypatch
) -> None:
    plan = _plan(tmp_path / "plans" / "demo")
    index = SqlitePlansIndex(tmp_path)
    index.refresh()
    connection_count = 0
    connect = index._connect

    def counted_connect():
        nonlocal connection_count
        connection_count += 1
        return connect()

    monkeypatch.setattr(index, "_connect", counted_connect)
    first = index.status_rows()
    first["plans"][0]["status"] = "changed by caller"
    second = index.status_rows()
    assert connection_count == 1
    assert second["plans"][0]["status"] == "active"

    plan.write_text(plan.read_text().replace("active", "completed"), encoding="utf-8")
    index.refresh()
    connections_before_read = connection_count
    third = index.status_rows()
    assert connection_count == connections_before_read + 1
    assert third["plans"][0]["status"] == "completed"


def test_unchanged_tree_skips_all_parsing(tmp_path: Path, monkeypatch) -> None:
    plan = _plan(tmp_path / "plans" / "demo")
    _backdate(plan)
    index = SqlitePlansIndex(tmp_path)
    calls = 0
    file_parser = files_plans_module.parse

    def counted(data):
        nonlocal calls
        calls += 1
        return file_parser(data)

    def fail_list(*args, **kwargs):
        raise AssertionError("refresh called FilesPlans.list")

    def fail_apply(*args, **kwargs):
        raise AssertionError("unchanged refresh staged database writes")

    monkeypatch.setattr(files_plans_module, "parse", counted)
    monkeypatch.setattr(plans_index_module, "parse", counted)
    monkeypatch.setattr(index._files, "list", fail_list)
    monkeypatch.setattr(plans_index_module, "_apply_changes", fail_apply)
    index.refresh()
    assert calls == 0


def test_unchanged_refresh_reuses_plan_activity_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    _backdate(_plan(tmp_path / "plans" / "demo"))
    original = plans_index_module._plan_activity_rows
    calls = 0

    def counted(root, plans):
        nonlocal calls
        calls += 1
        return original(root, plans)

    monkeypatch.setattr(plans_index_module, "_plan_activity_rows", counted)
    index = SqlitePlansIndex(tmp_path)
    index.refresh()
    index.refresh()

    assert calls == 1


def test_plan_activity_refreshes_after_cache_interval(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "plans" / "demo"
    plan = _plan(root)
    note = root / "notes" / "context.md"
    note.parent.mkdir()
    note.write_text("old", encoding="utf-8")
    _backdate(note)
    future = time.time() + 60
    os.utime(plan, (future, future))
    index = SqlitePlansIndex(tmp_path)
    monkeypatch.setattr(plans_index_module, "PLAN_ACTIVITY_REFRESH_SECONDS", 60.0)

    index.refresh()
    note.write_text("new", encoding="utf-8")
    index.refresh()
    assert index.activity_rows()[0]["latest_path"] == str(plan)

    monkeypatch.setattr(plans_index_module, "PLAN_ACTIVITY_REFRESH_SECONDS", 0.0)
    future = time.time() + 120
    os.utime(note, (future + 1, future + 1))
    index.refresh()
    assert index.activity_rows()[0]["latest_path"] == str(note)


def test_changed_artifact_is_parsed_once(tmp_path: Path, monkeypatch) -> None:
    plan = _plan(tmp_path / "plans" / "demo")
    index = SqlitePlansIndex(tmp_path)
    calls = 0
    parser = files_plans_module.parse

    def counted(data):
        nonlocal calls
        calls += 1
        return parser(data)

    monkeypatch.setattr(files_plans_module, "parse", counted)
    plan.write_text(
        plan.read_text().replace("A purpose.", "Changed."), encoding="utf-8"
    )
    index.refresh()
    assert calls == 1


def test_related_artifacts_refresh(tmp_path: Path) -> None:
    root = tmp_path / "plans" / "demo"
    plan = _plan(root)
    task = root / "tasks" / "01-build.md"
    task.parent.mkdir()
    task.write_text("---\nid: build\ntype: task\nstatus: todo\n---\n", encoding="utf-8")
    note = root / "notes" / "build.md"
    note.parent.mkdir()
    note.write_text("note", encoding="utf-8")
    (root / "review.md").write_text(
        "---\nverdict: approved\nreviewed_commit: abc\n---\n", encoding="utf-8"
    )
    (tmp_path / ".cache" / "plan-now").mkdir(parents=True)
    (tmp_path / ".cache" / "plan-now" / "demo.txt").write_text(
        "Working\n", encoding="utf-8"
    )
    index = SqlitePlansIndex(tmp_path)
    index.refresh()
    with sqlite3.connect(index.path) as db:
        assert db.execute("SELECT status FROM tasks").fetchone() == ("todo",)
        assert db.execute("SELECT verdict,reviewed_commit FROM reviews").fetchone() == (
            "approved",
            "abc",
        )
        assert db.execute("SELECT text FROM now_lines").fetchone() == ("Working",)
        assert db.execute("SELECT mtime_ns FROM task_notes").fetchone()[0] is not None
        note_mtime = db.execute("SELECT mtime_ns FROM task_notes").fetchone()[0]
    task.write_text("---\nid: build\ntype: task\nstatus: done\n---\n", encoding="utf-8")
    note.write_text("updated", encoding="utf-8")
    (root / "review.md").write_text("---\nverdict: rejected\n---\n", encoding="utf-8")
    (tmp_path / ".cache" / "plan-now" / "demo.txt").write_text(
        "New\n", encoding="utf-8"
    )
    assert index.refresh() > 0
    with sqlite3.connect(index.path) as db:
        assert db.execute("SELECT status FROM tasks").fetchone() == ("done",)
        assert db.execute("SELECT verdict FROM reviews").fetchone() == ("rejected",)
        assert db.execute("SELECT text FROM now_lines").fetchone() == ("New",)
        assert db.execute("SELECT mtime_ns FROM task_notes").fetchone()[0] != note_mtime
    task.unlink()
    plan.unlink()
    index.refresh()
    with sqlite3.connect(index.path) as db:
        assert db.execute("SELECT count(*) FROM tasks").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM reviews").fetchone() == (0,)


def test_newer_schema_refused_and_corrupt_database_rebuilt(tmp_path: Path) -> None:
    _plan(tmp_path / "plans" / "demo")
    index = SqlitePlansIndex(tmp_path)
    with sqlite3.connect(index.path) as db:
        db.execute("PRAGMA user_version=999")
    with pytest.raises(Invalid):
        SqlitePlansIndex(tmp_path)
    corrupt_root = tmp_path / "corrupt"
    _plan(corrupt_root / "plans" / "demo")
    corrupt_path = corrupt_root / ".cache" / "plans-read-index.sqlite3"
    corrupt_path.parent.mkdir(parents=True)
    corrupt_path.write_bytes(b"not sqlite")
    rebuilt = SqlitePlansIndex(corrupt_root)
    rebuilt.refresh()
    with sqlite3.connect(rebuilt.path) as db:
        assert db.execute("SELECT count(*) FROM plans").fetchone() == (1,)


def test_older_schema_rebuilds(tmp_path: Path) -> None:
    _plan(tmp_path / "plans" / "demo")
    index = SqlitePlansIndex(tmp_path)
    with sqlite3.connect(index.path) as db:
        db.execute("PRAGMA user_version=0")
    rebuilt = SqlitePlansIndex(tmp_path)
    with sqlite3.connect(rebuilt.path) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (6,)
        assert db.execute("SELECT count(*) FROM plans").fetchone() == (1,)


def test_reader_does_not_block_during_refresh(tmp_path: Path) -> None:
    plan = _plan(tmp_path / "plans" / "demo")
    index = SqlitePlansIndex(tmp_path)
    index.refresh()
    reader = sqlite3.connect(index.path, timeout=0.1)
    try:
        reader.execute("BEGIN")
        assert reader.execute("SELECT count(*) FROM plans").fetchone() == (1,)
        plan.write_text(
            plan.read_text().replace("A purpose.", "Changed."), encoding="utf-8"
        )
        index.refresh()
        assert reader.execute("SELECT purpose FROM plans").fetchone() == ("A purpose.",)
    finally:
        reader.close()


def _backdate(path: Path) -> None:
    old = time.time() - 10
    os.utime(path, (old, old))


def test_rebuild_after_refresh_keeps_rows(tmp_path: Path) -> None:
    _backdate(_plan(tmp_path / "plans" / "demo"))
    index = SqlitePlansIndex(tmp_path)
    before = index.refresh()
    after = index.rebuild()
    assert after > before
    with sqlite3.connect(index.path) as db:
        assert db.execute("SELECT count(*) FROM plans").fetchone() == (1,)


def test_fresh_index_refreshes_existing_rows_without_parsing(
    tmp_path: Path, monkeypatch
) -> None:
    plan = _plan(tmp_path / "plans" / "demo")
    task_dir = plan.parent / "tasks"
    task_dir.mkdir()
    (task_dir / "01.md").write_text("---\nid: t\ntype: task\n---\n", encoding="utf-8")
    (plan.parent / "review.md").write_text("---\nverdict: ok\n---\n", encoding="utf-8")
    note_dir = plan.parent / "notes"
    note_dir.mkdir()
    (note_dir / "01.md").write_text("note", encoding="utf-8")
    now_dir = tmp_path / ".cache" / "plan-now"
    now_dir.mkdir(parents=True)
    (now_dir / "demo.txt").write_text("now", encoding="utf-8")
    _backdate(plan)
    for source in (
        task_dir.iterdir(),
        (plan.parent / "review.md", *note_dir.iterdir(), *now_dir.iterdir()),
    ):
        for path in source:
            _backdate(path)
    SqlitePlansIndex(tmp_path).refresh()
    calls = 0
    parser = files_plans_module.parse

    def counted(data):
        nonlocal calls
        calls += 1
        return parser(data)

    monkeypatch.setattr(files_plans_module, "parse", counted)
    monkeypatch.setattr(plans_index_module, "parse", counted)

    def fail_read_bytes(self):
        raise AssertionError(f"read source bytes during no-op refresh: {self}")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)
    SqlitePlansIndex(tmp_path).refresh()
    assert calls == 0


def test_recent_artifact_is_rechecked_for_racy_timestamps(
    tmp_path: Path, monkeypatch
) -> None:
    plan = _plan(tmp_path / "plans" / "demo")
    index = SqlitePlansIndex(tmp_path)
    plan.write_text(plan.read_text().replace("active", "closed"), encoding="utf-8")
    calls = 0
    parser = files_plans_module.parse

    def counted(data):
        nonlocal calls
        calls += 1
        return parser(data)

    monkeypatch.setattr(files_plans_module, "parse", counted)
    index.refresh()
    index.refresh()
    assert calls >= 2


def test_generation_does_not_repeat_after_index_recreation(tmp_path: Path) -> None:
    _backdate(_plan(tmp_path / "plans" / "demo"))
    index = SqlitePlansIndex(tmp_path)
    first = index.refresh()
    index.rebuild()
    with sqlite3.connect(index.path) as db:
        second = db.execute("SELECT generation FROM meta").fetchone()[0]
    index.path.unlink()
    recreated = SqlitePlansIndex(tmp_path)
    with sqlite3.connect(recreated.path) as db:
        third = db.execute("SELECT generation FROM meta").fetchone()[0]
    assert first != second
    assert second != third


def test_directory_only_change_does_not_bump_generation(tmp_path: Path) -> None:
    _backdate(_plan(tmp_path / "plans" / "demo"))
    index = SqlitePlansIndex(tmp_path)
    generation = index.refresh()
    (tmp_path / "plans" / "demo" / "notes").mkdir()
    (tmp_path / "plans" / "demo" / "notes" / "scratch.txt").write_text("x")
    assert index.refresh() == generation


def test_standalone_task_is_removed_when_plan_appears(tmp_path: Path) -> None:
    root = tmp_path / "plans" / "demo"
    task = root / "task.md"
    task.parent.mkdir(parents=True)
    task.write_text("---\nid: standalone\ntype: task\n---\n", encoding="utf-8")
    _backdate(task)
    index = SqlitePlansIndex(tmp_path)
    index.refresh()
    _backdate(_plan(root))
    index.refresh()
    with sqlite3.connect(index.path) as db:
        assert db.execute(
            "SELECT count(*) FROM tasks WHERE path=?", (str(task),)
        ).fetchone() == (0,)
