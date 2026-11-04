import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_data.plan_state import open_plan_state
from varde_data.queue import open_queue
from varde_data.queue_line_sync import import_line_queue
from varde_data.queue_mode_lock import barrier, operation
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_workflow.cli import _parser
from varde_workflow.commands import now, plan_queue
from varde_workflow.queue_check import check_queue


def _task(
    plan: Path,
    name: str,
    status: str,
    owns: list[str],
    depends_on: list[str] | None = None,
) -> None:
    task = plan / "tasks" / f"{name}.md"
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_text(
        f"---\ntype: task\nstatus: {status}\n"
        f"owns: {owns!r}\ndepends_on: {(depends_on or [])!r}\n---\n",
        encoding="utf-8",
    )


def _plan(tmp_path: Path, queue: str) -> Path:
    plan = tmp_path / "plans" / "queue-plan"
    (plan / "notes").mkdir(parents=True)
    (plan / "plan.md").write_text("---\ntype: plan\nid: queue-plan\n---\n")
    (plan / "notes" / "queue.md").write_text(queue, encoding="utf-8")
    return plan


def test_queue_blocks_later_overlapping_owns_until_earlier_is_done(tmp_path: Path):
    plan = _plan(
        tmp_path,
        "alpha | fix:no | esc:0 | worktree:/tmp/alpha\n"
        "beta | fix:no | esc:0 | worktree:/tmp/beta\n",
    )
    _task(plan, "alpha", "in_progress", ["src/shared/**"])
    _task(plan, "beta", "todo", ["src/shared/b.py"])

    result = check_queue(plan)

    assert [item["task_id"] for item in result["items"]] == ["alpha", "beta"]
    assert result["items"][0]["blocked"] is False
    assert result["items"][1]["blocked_by"] == [
        {"kind": "owns_overlap", "task_id": "alpha", "status": "in_progress"}
    ]


def test_fixing_item_sorts_first_and_does_not_block_itself(tmp_path: Path):
    plan = _plan(
        tmp_path,
        "next | fix:no | esc:0 | worktree:/tmp/next\n"
        "repair | fix:yes | esc:1 | worktree:/tmp/repair\n",
    )
    _task(plan, "next", "todo", ["src/shared.py"])
    _task(plan, "repair", "fixing", ["src/shared.py"])

    items = check_queue(plan)["items"]

    assert [item["task_id"] for item in items] == ["repair", "next"]
    assert items[0]["blocked"] is False
    assert items[0]["blocked_by"] == []
    assert items[0]["escalation_count"] == 1
    assert items[1]["blocked_by"][0]["task_id"] == "repair"


def test_unmet_dependency_blocks_even_without_owns_overlap(tmp_path: Path):
    plan = _plan(tmp_path, "build | fix:no | esc:0 | worktree:-\n")
    _task(plan, "build", "todo", ["src/build.py"], ["setup"])
    _task(plan, "setup", "in_review", ["docs/setup.md"])

    item = check_queue(plan)["items"][0]

    assert item["blocked"] is True
    assert item["blocked_by"] == [
        {"kind": "depends_on", "task_id": "setup", "status": "in_review"}
    ]


def test_malformed_queue_line_has_location(tmp_path: Path):
    plan = _plan(tmp_path, "not a queue row\n")
    (plan / "tasks").mkdir()

    with pytest.raises(ValueError, match=r"queue.md:1: expected"):
        check_queue(plan)


def test_queue_reports_escalation_count_and_rejects_non_integer(tmp_path: Path):
    plan = _plan(tmp_path, "repair | fix:yes | esc:2 | worktree:/tmp/repair\n")
    _task(plan, "repair", "fixing", ["src/shared.py"])

    item = check_queue(plan)["items"][0]

    assert item["escalation_count"] == 2

    (plan / "notes" / "queue.md").write_text(
        "repair | fix:yes | esc:two | worktree:/tmp/repair\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match=r"queue.md:1: expected"):
        check_queue(plan)


def _set_queue_mode(plan: Path, mode: str) -> None:
    plans = next(parent for parent in plan.parents if parent.name == "plans")
    working = plans.parent
    if not (working / ".cache/data/queue.version").is_file():
        initialize(working)
    open_queue(working)
    with barrier(working), sqlite3.connect(working / QUEUE_DATABASE) as db:
        db.execute(
            "UPDATE queue_store_meta SET value=? WHERE key='store_mode'",
            (mode,),
        )


def test_sqlite_queue_check_displays_original_task_ids(tmp_path: Path):
    working = tmp_path / "working"
    plan = working / "plans" / "group" / "shared"
    (plan / "notes").mkdir(parents=True)
    (plan / "plan.md").write_text("---\ntype: plan\nid: shared\n---\n")
    (plan / "notes/queue.md").write_text(
        "later | fix:no | esc:0 | worktree:-\n"
        "first | fix:yes | esc:1 | worktree:/tmp/first\n"
    )
    _task(plan, "later", "todo", ["later.py"])
    _task(plan, "first", "fixing", ["first.py"])
    initialize(working)
    import_line_queue(plan)
    expected = check_queue(plan)

    _set_queue_mode(plan, "sqlite")

    actual = check_queue(plan)
    assert actual == expected
    assert [item["task_id"] for item in actual["items"]] == ["first", "later"]


def test_parity_with_real_task_files_and_strict_line_queue(tmp_path: Path):
    source = (
        Path(__file__).parent
        / "fixtures"
        / "plan-stores"
        / "plain"
        / "plans"
        / "sample-spikes"
    )
    working = tmp_path / "working"
    initialize(working)
    plan = working / "plans" / "copied-plan"
    (plan / "notes").mkdir(parents=True)
    (plan / "tasks").mkdir()
    (plan / "plan.md").write_text("---\ntype: plan\nid: copied-plan\n---\n")
    for task_file in sorted(source.joinpath("tasks").glob("*.md")):
        (plan / "tasks" / task_file.name).write_bytes(task_file.read_bytes())
    task_ids = [path.stem for path in sorted((plan / "tasks").glob("*.md"))]
    queue = "".join(
        f"{task_id} | fix:{'yes' if index == 0 else 'no'} | esc:{index} | worktree:-\n"
        for index, task_id in enumerate(task_ids)
    )
    (plan / "notes" / "queue.md").write_text(queue)
    import_line_queue(plan)

    markdown_result = check_queue(plan)
    _set_queue_mode(plan, "sqlite")
    sqlite_result = check_queue(plan)

    assert sqlite_result == markdown_result


def test_sqlite_queue_check_without_rows_fails(tmp_path: Path):
    plan = _plan(tmp_path, "task | fix:no | esc:0 | worktree:-\n")
    _task(plan, "task", "todo", [])
    _set_queue_mode(plan, "sqlite")

    with pytest.raises(ValueError, match="no queue items found for plan"):
        check_queue(plan)


def test_markdown_mode_does_not_create_database(tmp_path: Path):
    plan = _plan(tmp_path, "task | fix:no | esc:0 | worktree:-\n")
    _task(plan, "task", "todo", [])

    check_queue(plan)

    assert not (tmp_path / ".cache" / "data" / "queue.sqlite3").exists()
    assert not (tmp_path / ".cache").exists()


def test_sqlite_nonstrict_queue_uses_production_error(tmp_path: Path):
    working = tmp_path / "working"
    plan = working / "plans" / "group" / "shared"
    (plan / "notes").mkdir(parents=True)
    (plan / "tasks").mkdir()
    (plan / "plan.md").write_text("---\ntype: plan\nid: shared\n---\n")
    path = plan / "notes/queue.md"
    path.write_text("task | fix:no\n")
    _task(plan, "task", "todo", [])
    initialize(working)
    import_line_queue(plan)
    with pytest.raises(ValueError) as markdown_error:
        check_queue(plan)

    _set_queue_mode(plan, "sqlite")

    with pytest.raises(ValueError) as sqlite_error:
        check_queue(plan)
    assert str(sqlite_error.value) == str(markdown_error.value)


def test_sqlite_imported_malformed_queue_has_no_rows_error(tmp_path: Path):
    working = tmp_path / "working"
    plan = working / "plans" / "group" / "shared"
    (plan / "notes").mkdir(parents=True)
    (plan / "tasks").mkdir()
    (plan / "plan.md").write_text("---\ntype: plan\nid: shared\n---\n")
    path = plan / "notes/queue.md"
    path.write_text(
        "same | fix:no | esc:0 | worktree:-\n"
        "same | fix:yes | esc:1 | worktree:/tmp/same\n"
    )
    initialize(working)
    import_line_queue(plan)
    _set_queue_mode(plan, "sqlite")

    with pytest.raises(ValueError, match="no queue items found for plan"):
        check_queue(plan)


def test_queue_command_displays_escalation_count(tmp_path: Path, monkeypatch, capsys):
    plan = _plan(tmp_path, "repair | fix:yes | esc:2 | worktree:/tmp/repair\n")
    _task(plan, "repair", "fixing", ["src/shared.py"])
    monkeypatch.setattr(
        plan_queue.MemoryPaths,
        "resolve",
        lambda _cwd: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    monkeypatch.setattr(now, "resolve_plan", lambda *_args: plan / "plan.md")

    assert plan_queue.run(SimpleNamespace(plan="queue-plan", json=False)) == 0

    assert "repair ready (fixing) esc=2 worktree=/tmp/repair" in capsys.readouterr().out


def test_cli_routes_queue_check_with_plan_argument():
    args = _parser().parse_args(["plan", "queue", "check", "queue-plan", "--json"])

    assert args.command == "queue"
    assert args.queue_action == "check"
    assert args.plan == "queue-plan"
    assert args.json is True


def test_queue_check_reads_sqlite_items_and_canonical_task_status(tmp_path: Path):
    plan = tmp_path / "plans" / "queue-plan"
    (plan / "notes").mkdir(parents=True)
    (plan / "plan.md").write_text("---\ntype: plan\nid: queue-plan\n---\n")
    (plan / "tasks").mkdir()
    (plan / "notes" / "queue.md").write_text(
        "setup | fix:yes | esc:1 | worktree:-\n"
        "build | fix:no | esc:2 | worktree:/work/build\n"
    )
    _task(plan, "setup", "todo", ["src/setup.py"])
    _task(plan, "build", "todo", ["src/build.py"], ["setup"])
    initialize(tmp_path)
    import_line_queue(plan)
    _set_queue_mode(plan, "sqlite")
    database = tmp_path / QUEUE_DATABASE
    with operation(tmp_path):
        open_plan_state(database.parents[2]).set_task_state(
            str(plan.resolve()), "setup", "done", actor="test"
        )

    result = check_queue(plan)

    assert [item["task_id"] for item in result["items"]] == ["setup", "build"]
    assert result["items"][0]["status"] == "done"
    assert result["items"][1]["escalation_count"] == 2
    assert result["items"][1]["blocked"] is False
