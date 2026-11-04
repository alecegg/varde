from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from varde_data.config import DataConfig, load_data_config
from varde_data.open import open_data
from varde_workflow.collector_facts import CollectorFacts
from varde_workflow.commands.status import collect_status
from varde_workflow.commands.watch import collect_watch
from varde_workflow.git_facts import GitFacts

pytestmark = pytest.mark.slow

PLAN_COUNT = 800
TASK_COUNT = 3_500


def _write_scale_tree(working: Path) -> None:
    plans = working / "plans"
    now_dir = working / ".cache" / "plan-now"
    now_dir.mkdir(parents=True)
    task_counts = [4] * 700 + [7] * 100
    for plan_number, task_count in enumerate(task_counts):
        plan_id = f"scale-{plan_number:04d}"
        root = plans / plan_id
        (root / "tasks").mkdir(parents=True)
        (root / "notes").mkdir()
        (root / "plan.md").write_text(
            f"---\nid: {plan_id}\ntype: plan\nstatus: active\n"
            f"title: Scale {plan_number}\n---\n\n"
            "## Purpose\nSynthetic scale fixture.\n\n## Open questions\n- None\n",
            encoding="utf-8",
        )
        (root / "review.md").write_text(
            "---\nverdict: pending\nreviewed_commit: null\n---\n", encoding="utf-8"
        )
        (root / "notes" / "context.md").write_text("fixture note\n", encoding="utf-8")
        (now_dir / f"{plan_id}.txt").write_text(
            "Working on scale test\n", encoding="utf-8"
        )
        for task_number in range(task_count):
            task_id = f"task-{task_number:02d}"
            task = root / "tasks" / f"{task_id}.md"
            task.write_text(
                f"---\nid: {task_id}\ntype: task\nstatus: todo\n"
                f"title: {task_id}\n---\n",
                encoding="utf-8",
            )
            (root / "notes" / f"{task_id}.md").write_text(
                "task note\n", encoding="utf-8"
            )

    # The index skips caching files modified within its two-second stat-race
    # window. Age the fixture so repeated refreshes see stable files.
    stable_mtime = time.time_ns() - 60_000_000_000
    for path in sorted(working.rglob("*"), reverse=True):
        os.utime(path, ns=(stable_mtime, stable_mtime))
    os.utime(working, ns=(stable_mtime, stable_mtime))


def test_plans_index_handles_scale_fixture(tmp_path: Path) -> None:
    _write_scale_tree(tmp_path)
    config = load_data_config()
    sqlite_config = DataConfig(
        backends={**config.backends, "plans": "sqlite"},
        learn_store=config.learn_store,
    )
    index = open_data(tmp_path, sqlite_config).plans
    facts = CollectorFacts(
        GitFacts((), {}, frozenset(), {}, {}), (), (), {}, ("0", "0"), ()
    )

    generation = index.refresh()
    assert generation > 0
    stable_generation = index.refresh()
    status = collect_status(
        index, facts, now=time.time(), working=tmp_path, repo=tmp_path
    )
    watch = collect_watch(
        index, facts, now=time.time(), working=tmp_path, repo=tmp_path
    )
    assert len(index.plan_rows()) == PLAN_COUNT
    assert len(index.task_rows()) == TASK_COUNT

    assert len(status["plans"]) > 0
    assert isinstance(watch, list)
    # An unchanged refresh must be a no-op; the cached index still serves the
    # complete fixture through the collector and query APIs.
    assert index.refresh() == stable_generation
