from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from varde_data.backends.sqlite import plans_index
from varde_data.backends.sqlite.plans_index import SqlitePlansIndex

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

    # The parser deliberately avoids caching files inside its two-second
    # stat-race window. Age the fixture so repeated refreshes test stable files.
    stable_mtime = time.time_ns() - 3_000_000_000
    for path in sorted(working.rglob("*"), reverse=True):
        os.utime(path, ns=(stable_mtime, stable_mtime))
    os.utime(working, ns=(stable_mtime, stable_mtime))


def test_plans_index_scale_uses_bounded_parses_and_bulk_queries(
    tmp_path: Path, monkeypatch
) -> None:
    _write_scale_tree(tmp_path)
    parsed_paths: list[str] = []
    query_count = 0
    document_row = plans_index._document_row
    query_rows = plans_index._query_rows

    def count_documents(*args, **kwargs):
        parsed_paths.append(str(args[1]))
        return document_row(*args, **kwargs)

    def count_queries(*args, **kwargs):
        nonlocal query_count
        query_count += 1
        return query_rows(*args, **kwargs)

    monkeypatch.setattr(plans_index, "_document_row", count_documents)
    monkeypatch.setattr(plans_index, "_query_rows", count_queries)
    index = SqlitePlansIndex(tmp_path)
    assert index.refresh() > 0

    parses_after_build = len(parsed_paths)
    assert 0 < parses_after_build <= 2 * (PLAN_COUNT + TASK_COUNT)
    index.refresh()
    assert len(parsed_paths) == parses_after_build

    assert len(index.plan_rows()) == PLAN_COUNT
    assert len(index.task_rows()) == TASK_COUNT
    assert query_count == 2
