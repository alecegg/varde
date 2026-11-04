from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from varde_data.plan_state_sync import import_plan_dir
from varde_data.queue import open_queue
from varde_data.queue_mode_lock import operation
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.queue_sync import import_queue_md
from varde_data.records.queue import QueueItemInput
from varde_runner.config import ROLE_NAMES
from varde_runner.identity_profile import defaults
from varde_runner.role_queue_source import read_role_queue
from varde_runner.role_queue_sqlite import sqlite_role_queue

DATABASE = QUEUE_DATABASE
_HEADER = (
    "| id | plan dir | findings | owned files | "
    "depends_on / serialize-with | priority | state | planned_at | "
    "plan_reviewed_at | build_started_at | build_done_at | merged_at |"
)
_SEPARATOR = "|---|---|---|---|---|---|---|---|---|---|---|---|"


class Dashboard:
    """The dashboard shape the web route passes to the adapter."""

    def __init__(self, working: Path, plans: list[dict[str, str]]) -> None:
        self.cli = SimpleNamespace(cwd=working, env={})
        self.plans = plans

    def queue_inputs(self) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
        return {"plans": self.plans}, []


def _sources(
    working: Path,
    plans: list[dict[str, str]],
    *,
    agent_rows: list[dict[str, str]] | None = None,
) -> SimpleNamespace:
    dashboard = Dashboard(working, plans)
    return SimpleNamespace(
        queue_inputs=dashboard.queue_inputs,
        agent_rows=agent_rows or [],
        bindings={},
        profiles=defaults(ROLE_NAMES),
    )


def _write_plan(working: Path, plan_id: str, *, status: str, assigned_to: str) -> Path:
    plan = working / "plans" / plan_id
    plan.mkdir(parents=True)
    (plan / "plan.md").write_text(
        f"---\nstatus: {status}\nassigned_to: {assigned_to}\n---\n# {plan_id}\n",
        encoding="utf-8",
    )
    return plan


def _write_queue(plan: Path, rows: list[str]) -> Path:
    path = plan / "queue.md"
    path.write_text(
        "\n".join(["# Queue", "", _HEADER, _SEPARATOR, *rows, ""]),
        encoding="utf-8",
    )
    return path


def _set_mode(working: Path) -> None:
    initialize(working)
    with (
        operation(working),
        closing(sqlite3.connect(working / QUEUE_DATABASE)) as db,
        db,
    ):
        db.execute("UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'")


def _store(working: Path):
    _set_mode(working)
    return open_queue(working)


def _queue_row(identifier: str, plan_dir: str, title: str, state: str) -> str:
    return f"| {identifier} | {plan_dir} | {title} | | none | 1 | {state} | | | | | |"


def _fixture_plans() -> list[dict[str, str]]:
    return [
        {
            "id": "plan-a",
            "title": "Queue plan",
            "assigned_to": "builder",
            "status": "active",
        },
        {
            "id": "plan-b",
            "title": "Next plan",
            "assigned_to": "builder",
            "status": "backlog",
        },
    ]


def test_store_and_files_give_equal_role_queues_after_import(
    tmp_path: Path,
) -> None:
    working = tmp_path / "working"
    plan_a = _write_plan(working, "plan-a", status="active", assigned_to="builder")
    plan_b = _write_plan(working, "plan-b", status="backlog", assigned_to="builder")
    queue = _write_queue(
        plan_a,
        [
            _queue_row("plan-a", "plans/plan-a", "Queue plan", "building"),
            _queue_row("plan-b", "plans/plan-b", "Next plan", "queued"),
        ],
    )
    _set_mode(working)
    import_queue_md(queue, "bundle")
    import_plan_dir(working, plan_a)
    import_plan_dir(working, plan_b)
    sources = _sources(
        working,
        _fixture_plans(),
        agent_rows=[
            {
                "session_id": "session-1",
                "agent_id": "agent-1",
                "role": "builder",
                "lifecycle": "running",
            }
        ],
    )

    from_files = read_role_queue(sources)
    _set_mode(working)
    from_store = read_role_queue(sources)

    assert from_store == from_files
    assert from_store == sqlite_role_queue(sources)

    _store(working).enqueue(
        QueueItemInput(
            id="store-only",
            plan_dir="plans/plan-b",
            role="builder",
            findings="Store only",
            queue_name="bundle",
            row_order=3,
        )
    )
    assert "store-only" in {row.id for row in read_role_queue(sources).rows["builder"]}


def test_each_store_state_maps_to_one_row_state(tmp_path: Path) -> None:
    working = tmp_path / "working"
    working.mkdir()
    store = _store(working)
    expected = {
        "queued": "waiting",
        "claimed": "running",
        "building": "running",
        "in_review": "running",
        "blocked": "blocked",
        "merged": "done",
    }
    for order, state in enumerate(expected):
        store.enqueue(
            QueueItemInput(
                id=f"item-{state}",
                plan_dir="plans/plan-a",
                role="builder",
                state=state,
                queue_name="bundle",
                row_order=order,
            )
        )
    _set_mode(working)

    rows = sqlite_role_queue(_sources(working, [])).rows["builder"]

    assert [(row.id, row.state) for row in rows] == [
        (f"item-{state}", mapped) for state, mapped in expected.items()
    ]


def test_cancelled_rows_are_omitted(tmp_path: Path) -> None:
    working = tmp_path / "working"
    working.mkdir()
    store = _store(working)
    store.enqueue(
        QueueItemInput(
            id="kept",
            plan_dir="plans/plan-a",
            role="builder",
            state="queued",
            queue_name="bundle",
        )
    )
    store.enqueue(
        QueueItemInput(
            id="cancelled",
            plan_dir="plans/plan-a",
            role="builder",
            state="cancelled",
            queue_name="bundle",
        )
    )
    _set_mode(working)

    queues = sqlite_role_queue(_sources(working, []))

    assert [row.id for row in queues.rows["builder"]] == ["kept"]


def test_role_falls_back_to_plan_state_assignment(tmp_path: Path) -> None:
    working = tmp_path / "working"
    plan = _write_plan(working, "plan-a", status="active", assigned_to="reviewer")
    _set_mode(working)
    import_plan_dir(working, plan)
    store = _store(working)
    store.enqueue(
        QueueItemInput(
            id="bare-name",
            plan_dir="plan-a",
            findings="Review plan A",
            queue_name="bundle",
            row_order=0,
        )
    )
    store.enqueue(
        QueueItemInput(
            id="working-relative",
            plan_dir="plans/plan-a",
            findings="Review plan A again",
            queue_name="bundle",
            row_order=1,
        )
    )
    store.enqueue(
        QueueItemInput(
            id="explicit",
            plan_dir="plans/plan-a",
            role="builder",
            queue_name="bundle",
            row_order=2,
        )
    )
    store.enqueue(
        QueueItemInput(
            id="orphan",
            plan_dir="plans/missing",
            queue_name="bundle",
            row_order=3,
        )
    )
    _set_mode(working)

    queues = sqlite_role_queue(_sources(working, []))

    assert [row.id for row in queues.rows["reviewer"]] == [
        "bare-name",
        "working-relative",
    ]
    assert queues.rows["reviewer"][0].plan_id == "plan-a"
    assert [row.id for row in queues.rows["builder"]] == ["explicit"]
    assert "orphan" not in {row.id for rows in queues.rows.values() for row in rows}


def test_empty_store_gives_idle_roles(tmp_path: Path) -> None:
    working = tmp_path / "working"
    working.mkdir()
    _set_mode(working)

    queues = sqlite_role_queue(_sources(working, []))

    assert queues.roles
    assert {summary.state for summary in queues.roles} == {"idle"}
    assert all(not rows for rows in queues.rows.values())


def test_markdown_mode_reads_files_without_a_database(tmp_path: Path) -> None:
    working = tmp_path / "working"
    working.mkdir()
    sources = _sources(
        working,
        [
            {
                "id": "plan-a",
                "title": "Queue plan",
                "assigned_to": "builder",
                "status": "active",
            }
        ],
    )

    result = read_role_queue(sources)

    assert not (working / DATABASE).exists()
    builder = next(summary for summary in result.roles if summary.role == "builder")
    assert builder.state == "running"
    assert builder.current is not None
    assert builder.current.title == "Queue plan"


def test_building_store_item_with_a_failed_agent_makes_the_role_failed(
    tmp_path: Path,
) -> None:
    working = tmp_path / "working"
    working.mkdir()
    _store(working).enqueue(
        QueueItemInput(
            id="item-1",
            plan_dir="plans/plan-a",
            role="builder",
            findings="Add role status card",
            state="building",
            queue_name="bundle",
        )
    )
    _set_mode(working)
    sources = _sources(
        working,
        [],
        agent_rows=[
            {
                "session_id": "session-1",
                "agent_id": "agent-1",
                "role": "builder",
                "lifecycle": "failed",
            }
        ],
    )

    builder = next(
        summary
        for summary in sqlite_role_queue(sources).roles
        if summary.role == "builder"
    )

    assert builder.state == "failed"
    assert builder.current is not None
    assert builder.current.title == "Add role status card"
