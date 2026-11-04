from __future__ import annotations

import io
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from varde_learn.loop import analyzed
from varde_learn.loop.cli_sweep import run as run_cli
from varde_learn.loop.diagnose.list import ListedSession, ListedWorker
from varde_learn.loop.friction_repository import open_repository
from varde_learn.loop.sweep import run


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(  # noqa: S603 - fixed Git init for temporary fixture.
        [  # noqa: S607 - run installed Git for the temporary repository.
            "git",
            "init",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _session(session_id: str) -> dict:
    return {
        "harness": "codex",
        "session_id": session_id,
        "path": "/tmp/session.jsonl",  # noqa: S108 - stable synthetic session path.
        "workers": [],
    }


def _patch_store(monkeypatch, store: Path, repos: list[Path], sessions_by_repo):
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    monkeypatch.setattr(run, "configured_repos", lambda: repos)
    monkeypatch.setattr(run, "_roots", dict)
    monkeypatch.setattr(
        run,
        "_sessions",
        lambda repo, _roots: (sessions_by_repo.get(repo, []), []),
    )
    monkeypatch.setattr(
        run,
        "_inspect",
        lambda session, _roots: (
            {"command_failures": {"pytest": {"calls": 3, "failures": 1}}},
            [],
        ),
    )
    monkeypatch.setattr(run, "summary_config", lambda: (False, 100))


def test_real_store_dedupes_findings_and_keeps_daily_digest(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    nested_repo = _git_repo(tmp_path / "nested-repo")
    store = tmp_path / "learn-store"
    first = _session("first")
    second = _session("second")
    sessions_by_repo = {repo: [first], nested_repo: [first]}
    _patch_store(monkeypatch, store, [repo, nested_repo], sessions_by_repo)

    calls = []
    inspect = run._inspect

    def track_inspect(session, roots):
        calls.append(session["session_id"])
        return inspect(session, roots)

    monkeypatch.setattr(run, "_inspect", track_inspect)
    first_run = run.run_sweep()
    assert first_run["sessions_seen"] == 1
    assert first_run["analyzed"] == 1
    assert first_run["friction_added"] == 1
    assert calls == ["first"]

    sessions_by_repo[repo] = [first, second]
    sessions_by_repo[nested_repo] = []
    second_run = run.run_sweep()
    assert second_run["analyzed"] == 1
    assert second_run["friction_added"] == 0
    assert analyzed.seen(store, "codex") == {"first", "second"}
    assert len(open_repository(store).event_log().state.items) == 1

    digest_path = (
        store / "digests" / f"{date.fromisoformat(second_run['run_at'][:10])}.json"
    )
    digest_before = digest_path.read_bytes()
    sessions_by_repo[repo] = [first, second]
    third_run = run.run_sweep()
    assert third_run["analyzed"] == 0
    assert third_run["digest"]["text"] == second_run["digest"]["text"]
    assert digest_path.read_bytes() == digest_before


def test_invalid_summary_config_is_recorded_without_aborting_ledger_writes(
    tmp_path, monkeypatch
):
    repo = _git_repo(tmp_path / "repo")
    store = tmp_path / "learn-store"
    session = _session("session")
    _patch_store(monkeypatch, store, [repo], {repo: [session]})
    monkeypatch.setattr(
        run, "summary_config", lambda: (_ for _ in ()).throw(ValueError("bad cap"))
    )

    result = run.run_sweep()

    assert result["analyzed"] == 1
    assert result["summary_error"] == "invalid summary config: bad cap"
    assert analyzed.seen(store, "codex") == {"session"}


def test_dry_run_json_cli_contract(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    store = tmp_path / "learn-store"
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    monkeypatch.setattr(run, "configured_repos", lambda: [repo])
    monkeypatch.setattr(run, "_roots", dict)
    monkeypatch.setattr(
        run, "_sessions", lambda _repo, _roots: ([_session("fresh")], [])
    )
    output = io.StringIO()
    error = io.StringIO()

    assert (
        run_cli(
            ["sweep", "--dry-run", "--json"],
            SimpleNamespace(stdout=output, stderr=error),
        )
        == 0
    )
    envelope = json.loads(output.getvalue())
    assert envelope["ok"] is True
    assert envelope["data"]["sessions"] == [_session("fresh")]
    assert envelope["data"]["analyzed"] == 0
    assert error.getvalue() == ""


def test_sweep_help_uses_help_resource():
    from varde_learn.loop.help import help_text

    output = io.StringIO()
    assert run_cli(["--help"], SimpleNamespace(stdout=output)) == 0
    assert output.getvalue() == help_text("sweep")


def test_sweep_text_summary_reports_warning_count(monkeypatch):
    monkeypatch.setattr(
        run,
        "run_sweep",
        lambda **_kwargs: {
            "analyzed": 0,
            "skipped": 0,
            "friction_added": 0,
            "failures": [],
            "warnings": ["discovery incomplete"],
        },
    )
    output = io.StringIO()

    assert run_cli([], SimpleNamespace(stdout=output)) == 0

    assert "0 failures, 1 warning" in output.getvalue()


def test_sweep_import_registers_all_harness_adapters_in_fresh_process():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from varde_learn.loop.sweep import run; "
                "from varde_learn.loop.diagnose.model import HARNESS_ADAPTERS; "
                "assert {'codex', 'claude', 'opencode'} == "
                "{harness.value for harness in HARNESS_ADAPTERS}"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_listing_warnings_are_reported_separately_from_failures(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        run,
        "list_sessions",
        lambda _request: SimpleNamespace(
            sessions=[], warnings=["opencode discovery failed: denied"]
        ),
    )

    listed, failures, warnings = run._list_sessions(
        [repo], {"codex": repo, "claude": repo, "opencode": repo}
    )

    assert listed == []
    assert failures == []
    assert warnings == ["opencode discovery failed: denied"]


def test_listing_dedupes_130_identical_warnings_across_repos(tmp_path, monkeypatch):
    repos = [_git_repo(tmp_path / f"repo-{index}") for index in range(2)]
    warning = "opencode discovery failed: denied"
    monkeypatch.setattr(
        run,
        "_sessions",
        lambda _repo, _roots: ([], [warning] * 65),
    )

    listed, failures, warnings = run._list_sessions(
        repos, {"codex": repos[0], "claude": repos[0], "opencode": repos[0]}
    )

    assert listed == []
    assert failures == []
    assert warnings == [warning]


def test_listed_dataclasses_convert_to_candidate_dicts_with_workers(
    tmp_path, monkeypatch
):
    repo = _git_repo(tmp_path / "repo")
    session = ListedSession(
        harness="codex",
        session_id="root",
        source="active",
        link=None,
        started_at=None,
        cwd=str(repo),
        root=True,
        workers=[
            ListedWorker(
                harness="claude",
                session_id="worker",
                source="active",
                link=None,
                path="/tmp/worker.jsonl",  # noqa: S108 - stable synthetic session path.
            )
        ],
        path="/tmp/root.jsonl",  # noqa: S108 - stable synthetic session path.
    )
    monkeypatch.setattr(run, "_sessions", lambda _repo, _roots: ([session], []))

    listed, failures, warnings = run._list_sessions(
        [repo], {"codex": repo, "claude": repo, "opencode": repo}
    )
    candidates, repo_for = run._select_candidates(listed, [], None)

    assert failures == []
    assert warnings == []
    assert [candidate["session_id"] for candidate in candidates] == ["root", "worker"]
    assert candidates[0]["workers"][0]["session_id"] == "worker"
    assert repo_for[("claude", "worker")] == str(repo)


def _skill_records():
    return [
        {
            "kind": "tool_call",
            "tool_name": "Skill",
            "tool_input_excerpt": json.dumps({"skill": "varde-plan"}),
            "tool_use_id": "s1",
        },
        {
            "kind": "tool_call",
            "tool_name": "Bash",
            "tool_input_excerpt": json.dumps({"command": "false"}),
            "tool_error": "boom",
        },
    ]


def test_inspect_stores_skills_only_when_a_skill_ran(monkeypatch):
    records = _skill_records()
    adapter = SimpleNamespace(inspect=lambda _request: SimpleNamespace(records=records))
    monkeypatch.setattr(run, "harness_adapter", lambda _name: adapter)
    session = {**_session("s"), "path": None}
    roots = {"codex": Path("/nonexistent")}

    metrics, _ = run._inspect(session, roots)
    assert metrics["skills"]["varde-plan"]["suspected_skip"] is True
    assert metrics["skills"]["varde-plan"]["loads"] == []

    records.clear()
    metrics, _ = run._inspect(session, roots)
    assert "skills" not in metrics


def test_ledger_rows_with_and_without_skills_both_read(tmp_path):
    analyzed.mark(tmp_path, "codex", "a", "2026-10-30T00:00:00+00:00", "x", {})
    analyzed.mark(
        tmp_path,
        "codex",
        "b",
        "2026-10-30T00:00:00+00:00",
        "x",
        {"skills": {"varde-plan": {"loads": [], "post_errors": 0}}},
    )
    rows = {row["session"]: row for row in analyzed.read_all(tmp_path)}
    assert "skills" not in rows["a"].get("metrics", {})
    assert "varde-plan" in rows["b"]["metrics"]["skills"]


def test_sweep_prunes_used_calls_and_reports_the_count(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from varde_data import calls_store
    from varde_data.calls import open_calls
    from varde_data.learn_store_mode import flip_domain_locked

    store = tmp_path / "learn-store"
    store.mkdir()
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    flip_domain_locked(store, "calls", "sqlite")
    now = datetime.now(UTC)
    for days in (60, 50, 1):
        open_calls(store).append(
            {
                "ts": (now - timedelta(days=days)).isoformat(),
                "command": "plan status",
                "status": "success",
                "duration_s": 0.1,
                "session": None,
            }
        )
    calls_store.mark_used(store, now.isoformat())
    _patch_store(monkeypatch, store, [], {})

    assert run.run_sweep(dry_run=True)["calls_pruned"] == 0
    result = run.run_sweep()

    assert result["calls_pruned"] == 2
    assert not [w for w in result["warnings"] if "prune" in str(w)]
