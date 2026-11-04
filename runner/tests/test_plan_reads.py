from __future__ import annotations

import asyncio
import os
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_web import app_request
from varde_data.plans import open_fresh_plans
from varde_runner.plan_reads import PlanReads
from varde_runner.relay import DataRelay
from varde_runner.varde_cli import VardeCLI
from varde_runner.web import app as web_app
from varde_runner.web import create_app
from varde_workflow.collectors import CollectorFacts, GitFacts


def _facts(bindings: tuple[dict, ...]) -> CollectorFacts:
    return CollectorFacts(
        GitFacts((), {}, frozenset(), {}, {}), (), bindings, {}, ("0", "0"), ()
    )


def test_plan_reads_keep_last_good_snapshot_while_refresh_runs(tmp_path, monkeypatch):
    reads = PlanReads(tmp_path, tmp_path)
    reads.index = object()
    reads.facts = _facts(({"address": "agent-old"},))
    started = threading.Event()
    release = threading.Event()

    def refresh():
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr(reads, "refresh_once", refresh)
    worker = threading.Thread(target=reads.refresh_once)
    worker.start()
    assert started.wait(timeout=1)
    assert reads.bindings() == [{"address": "agent-old"}]
    release.set()
    worker.join(timeout=1)
    assert not worker.is_alive()


def test_plan_reads_refresh_error_keeps_last_good_snapshot(tmp_path, monkeypatch):
    reads = PlanReads(tmp_path, tmp_path)

    def fail_refresh():
        raise OSError("offline")

    reads.index = SimpleNamespace(refresh=fail_refresh)
    reads.facts = _facts(({"address": "agent-old"},))
    last_index = reads.index
    last_facts = reads.facts

    def fail_git(_repo):
        raise OSError("git offline")

    def fail_facts(_working, _git):
        raise OSError("messages offline")

    monkeypatch.setattr("varde_runner.plan_reads.get_git_facts", fail_git)
    monkeypatch.setattr("varde_runner.plan_reads.gather_collector_facts", fail_facts)

    reads.refresh_once()

    assert reads.index is last_index
    assert reads.facts is not None
    assert reads.facts.bindings == last_facts.bindings
    assert reads.bindings() == [{"address": "agent-old"}]


def test_start_publishes_persisted_index_before_background_refresh(
    tmp_path, monkeypatch
):
    working = tmp_path / "working"
    plan = working / "plans" / "alpha" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntype: plan\nid: alpha\ntitle: Alpha\nstatus: active\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    env = {"VARDE_PLANS_BACKEND": "sqlite", "VARDE_WORKING_DIR": str(working)}
    created = PlanReads(working, Path.cwd(), env)
    created.refresh_once()

    reads = PlanReads(working, Path.cwd(), env)
    entered = threading.Event()
    release = threading.Event()

    def background_loop():
        entered.set()
        release.wait(timeout=3)

    monkeypatch.setattr(reads, "_run", background_loop)
    reads.start()
    try:
        assert entered.wait(timeout=1)
        assert reads.ready
        assert reads.snapshot_marker()["as_of"] is not None
        assert any(row["id"] == "alpha" for row in reads.status()["plans"])
        assert reads.detail_records("alpha") is not None
    finally:
        release.set()
        reads.stop()


def test_first_queue_request_uses_persisted_index(tmp_path, monkeypatch):
    working = tmp_path / "working"
    plan = working / "plans" / "alpha" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntype: plan\nid: alpha\ntitle: Alpha\nstatus: backlog\n"
        "category: fixes\n---\n",
        encoding="utf-8",
    )
    open_fresh_plans(working)
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    cli = VardeCLI(cwd=working, env={"VARDE_WORKING_DIR": str(working)})
    app = create_app(data_dir=tmp_path / "runner-data", cli=cli, agents=list)
    reads = app.state.dashboard.plan_reads
    reads.start()
    try:
        result = app_request(app, "GET", "/api/queue")
        assert result.status_code == 200
        assert any(
            row["id"] == "alpha"
            for category in result.json()["categories"]
            for row in category["waiting"]
        )
    finally:
        reads.stop()


def test_create_app_does_not_project_inbox_synchronously(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "working"))

    def fail_project(_self):
        raise AssertionError("create_app projected inbox before the listener started")

    monkeypatch.setattr("varde_runner.intake.InboxProjector.project", fail_project)
    app = create_app(
        data_dir=tmp_path / "runner-data",
        cli=VardeCLI(
            cwd=tmp_path / "working",
            env={"VARDE_WORKING_DIR": str(tmp_path / "working")},
        ),
        agents=list,
    )
    assert app.state.projector.last_messages == []


def test_plan_detail_during_deleted_index_rebuild_is_not_not_found(
    tmp_path, monkeypatch
):
    working = tmp_path / "working"
    plan = working / "plans" / "alpha" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntype: plan\nid: alpha\ntitle: Alpha\nstatus: active\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    cli = VardeCLI(cwd=working, env={"VARDE_WORKING_DIR": str(working)})
    app = create_app(data_dir=tmp_path / "runner-data", cli=cli, agents=list)
    reads = app.state.dashboard.plan_reads
    entered = threading.Event()
    release = threading.Event()

    def wait_for_release():
        entered.set()
        release.wait(timeout=2)

    monkeypatch.setattr(reads, "_run", wait_for_release)
    reads.start()
    try:
        assert entered.wait(timeout=1)
        response = app_request(app, "GET", "/api/plans/alpha")
        assert response.status_code == 503
    finally:
        release.set()
        reads.stop()


def test_plan_reads_can_restart_after_stop(tmp_path, monkeypatch):
    reads = PlanReads(tmp_path, tmp_path, {"VARDE_PLANS_BACKEND": "sqlite"})
    starts = []

    def loop():
        starts.append(True)
        reads._stop.wait(timeout=2)

    monkeypatch.setattr(reads, "_run", loop)
    reads.start()
    first = reads._thread
    reads.stop()
    assert first is not None and not first.is_alive()

    reads.start()
    second = reads._thread
    reads.stop()

    assert second is not None and second is not first
    assert len(starts) == 2


def test_runner_plan_routes_do_not_spawn_plan_cli(tmp_path, monkeypatch):
    working = tmp_path / "working"
    plan = working / "plans" / "alpha" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntype: plan\nid: alpha\ntitle: Alpha\nstatus: active\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VARDE_PLANS_BACKEND", "sqlite")
    cli = VardeCLI(cwd=working, env={"VARDE_WORKING_DIR": str(working)})
    app = create_app(data_dir=tmp_path / "runner-data", cli=cli, agents=list)
    app.state.dashboard.plan_reads.refresh_once()
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        raise AssertionError(f"request path spawned subprocess: {args}")

    monkeypatch.setattr(subprocess, "run", run)

    assert app_request(app, "GET", "/api/orchestrators").status_code == 200
    assert app_request(app, "GET", "/api/queue").status_code == 200
    assert app_request(app, "GET", "/api/plans/alpha").status_code == 200
    relay = DataRelay(working, plan_watch=app.state.dashboard.plan_reads.watch)
    asyncio.run(relay._refresh_plans())
    assert calls == []


def test_queue_and_owner_adapters_use_plan_reads(tmp_path, monkeypatch):
    working = tmp_path / "working"
    plan = working / "plans" / "alpha"
    (plan / "tasks").mkdir(parents=True)
    (plan / "plan.md").write_text(
        "---\ntype: plan\nid: alpha\ntitle: Alpha\n"
        "status: active\nowner: owner-a\n---\n",
        encoding="utf-8",
    )
    (plan / "tasks" / "one.md").write_text(
        "---\ntype: task\nid: one\ntitle: One\nstatus: todo\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    cli = VardeCLI(cwd=working, env={"VARDE_WORKING_DIR": str(working)})
    reads = PlanReads(working, Path.cwd(), {"VARDE_PLANS_BACKEND": "sqlite"})
    reads.refresh_once()
    cli.plan_reads = reads

    def fail(*_args, **_kwargs):
        raise AssertionError("CLI plan reader was called")

    cli.read_plan_tasks = fail
    cli.read_plan_graph = fail
    cli.read_plan_summary = fail
    monkeypatch.setattr(subprocess, "run", fail)

    assert web_app._queue({"id": "alpha"}, cli) == [
        {
            "id": "one",
            "title": "One",
            "status": "todo",
            "status_at": None,
            "owner": None,
            "owner_inherited": False,
        }
    ]
    assert web_app._plan_owner("alpha", cli) == "owner-a"


def test_files_backend_is_explicit_rollback(tmp_path):
    reads = PlanReads(
        tmp_path,
        tmp_path,
        {"VARDE_PLANS_BACKEND": "files"},
    )

    reads.start()

    assert reads.enabled is False
    assert reads.index is None


def test_runner_readers_match_old_cli_on_real_tree_copy(monkeypatch, tmp_path):
    copy = os.environ.get("VARDE_REAL_PLANS_COPY")
    if copy is None:
        pytest.skip("set VARDE_REAL_PLANS_COPY to a temporary real working-tree copy")
    working = Path(copy).resolve()
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    cli = VardeCLI(cwd=Path.cwd(), env={"VARDE_WORKING_DIR": str(working)})
    expected_status = cli.read_plan_status()
    expected_watch = cli.read_plan_watch()

    reads = PlanReads(working, Path.cwd(), {"VARDE_PLANS_BACKEND": "sqlite"})
    reads.refresh_once()

    assert _without_clock_fields(reads.status()) == _without_clock_fields(
        expected_status
    )
    assert _without_clock_fields(reads.watch()) == _without_clock_fields(expected_watch)


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
