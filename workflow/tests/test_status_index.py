from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

from golden.plans.builder import FIXED_CLOCK, build
from varde_data.plans import open_fresh_plans
from varde_workflow.collector_facts import gather_collector_facts
from varde_workflow.commands import status, watch
from varde_workflow.git_facts import get_git_facts


def test_status_index_rows_match_files_collector(tmp_path: Path, monkeypatch) -> None:
    working, repo = build(tmp_path)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(working)
    monkeypatch.setattr(status.time, "time", lambda: FIXED_CLOCK)
    expected = status.collect_from(working, now=FIXED_CLOCK, repo=repo)
    handle = open_fresh_plans(working)
    actual = status.collect_status(
        handle,
        gather_collector_facts(working, get_git_facts(repo, refresh=True)),
        now=FIXED_CLOCK,
        working=working,
        repo=repo,
    )
    actual = status.add_open_comments(
        actual, working, handle.list(include_tasks=False).records
    )
    assert actual == expected, (
        [(row["id"], row["group"], row["unit"]) for row in expected["plans"]],
        [(row["id"], row["group"], row["unit"]) for row in actual["plans"]],
        _diff(expected, actual),
    )
    assert all("raw" not in row for row in handle.plan_rows())


def test_watch_index_rows_match_files_collector(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    working, repo = build(tmp_path)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    handle = open_fresh_plans(working)
    facts = gather_collector_facts(working, get_git_facts(repo, refresh=True))
    expected = watch.scan(working, repo, FIXED_CLOCK, 1200)
    actual = watch.collect_watch(
        handle,
        facts,
        now=FIXED_CLOCK,
        threshold_secs=1200,
        working=working,
        repo=repo,
    )
    assert actual == expected, _diff(expected, actual)
    old_events, _ = watch.frame_events(expected, FIXED_CLOCK, 1200)
    first = old_events[0].to_json() if old_events else {"kind": "snapshot"}
    expected_json = {
        **first,
        "plans": expected,
        "events": [event.to_json() for event in old_events],
    }
    assert (
        watch.run_watch(
            SimpleNamespace(
                working=working,
                repo=repo,
                once=True,
                no_inbox=True,
                no_wake=True,
                stale=1200,
                notes=None,
                json=True,
                interval=60,
            ),
            clock=lambda: FIXED_CLOCK,
        )
        == 0
    )
    actual_json = json.loads(capsys.readouterr().out)
    assert _without_clock_fields(actual_json) == _without_clock_fields(expected_json)


def test_watch_refreshes_index_and_facts_between_frames(
    tmp_path: Path, monkeypatch
) -> None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.records.messages import NewMessage

    working = tmp_path / "working"
    repo = tmp_path
    plan = working / "plans" / "live" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\nid: live\ntype: plan\ntitle: Live\nstatus: active\n---\n",
        encoding="utf-8",
    )
    frames = []

    def capture(handle, facts, **_kwargs):
        frames.append((handle.status_rows()["plans"][0]["status"], len(facts.messages)))
        return []

    monkeypatch.setattr(watch, "collect_watch", capture)
    changed = False

    def edit_between_frames(_seconds):
        nonlocal changed
        if changed:
            return
        changed = True
        plan.write_text(
            "---\nid: live\ntype: plan\ntitle: Live\nstatus: completed\n---\n",
            encoding="utf-8",
        )
        open_data(working, load_data_config()).messages.append(
            NewMessage("builder", "main", "info", "finished", ts="2026-10-24T00:00:00Z")
        )

    args = SimpleNamespace(
        working=working,
        repo=repo,
        once=False,
        no_inbox=True,
        no_wake=True,
        stale=1200,
        notes=None,
        json=False,
        interval=0,
    )
    assert watch.run_watch(args, frame_limit=2, sleep=edit_between_frames) == 0

    assert frames == [("active", 0), ("completed", 1)]


def test_real_tree_copy_matches_files_collectors(monkeypatch) -> None:
    copy = os.environ.get("VARDE_REAL_PLANS_COPY")
    if copy is None:
        import pytest

        pytest.skip("set VARDE_REAL_PLANS_COPY to a temporary real working-tree copy")
    working = Path(copy)
    repo = Path.cwd()
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    handle = open_fresh_plans(working)
    facts = gather_collector_facts(working, get_git_facts(repo, refresh=True))
    timestamp = time.time()
    monkeypatch.setattr(status.time, "time", lambda: timestamp)
    old_status = status.collect_from(working, now=timestamp, repo=repo)
    new_status = status.collect_status(
        handle, facts, now=timestamp, working=working, repo=repo
    )
    old_status_json = _without_clock_fields(old_status)
    new_status_json = _without_clock_fields(new_status)
    assert old_status_json == new_status_json, _diff(old_status_json, new_status_json)
    old_watch = watch.scan(working, repo, timestamp)
    new_watch = watch.collect_watch(
        handle, facts, now=timestamp, working=working, repo=repo
    )
    assert _without_clock_fields(old_watch) == _without_clock_fields(new_watch)


def test_collectors_do_not_access_filesystem_or_git(
    tmp_path: Path, monkeypatch
) -> None:
    working, repo = build(tmp_path)
    handle = open_fresh_plans(working)
    facts = gather_collector_facts(working, get_git_facts(repo, refresh=True))

    def fail_io(*_args, **_kwargs):
        raise AssertionError("collector performed filesystem or Git I/O")

    monkeypatch.setattr(Path, "stat", fail_io)
    monkeypatch.setattr(Path, "iterdir", fail_io)
    monkeypatch.setattr(Path, "read_bytes", fail_io)
    monkeypatch.setattr(Path, "rglob", fail_io)
    monkeypatch.setattr("varde_workflow.execution_wave_tools.git", fail_io)
    status.collect_status(handle, facts, now=FIXED_CLOCK, working=working, repo=repo)
    watch.collect_watch(handle, facts, now=FIXED_CLOCK, working=working, repo=repo)


def _diff(expected, actual):
    if isinstance(expected, dict) and isinstance(actual, dict):
        return {
            key: _diff(expected.get(key), actual.get(key))
            for key in expected.keys() | actual.keys()
            if expected.get(key) != actual.get(key)
        }
    if isinstance(expected, list) and isinstance(actual, list):
        return [
            _diff(left, right)
            for left, right in zip(expected, actual, strict=False)
            if left != right
        ]
    return expected, actual


def _without_clock_fields(value):
    ignored = {"now_at", "newest_activity", "last_event_at"}
    if isinstance(value, dict):
        return {
            key: _without_clock_fields(item)
            for key, item in value.items()
            if key not in ignored
        }
    if isinstance(value, list):
        return [_without_clock_fields(item) for item in value]
    return value
