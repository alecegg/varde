from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from varde_data.views.status import TASK_ACTIVE as VIEW_TASK_ACTIVE
from varde_workflow.commands import now, readiness, status
from varde_workflow.schema import TASK_ACTIVE


def write_artifact(path: Path, frontmatter: str, body: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return path


def _append_messages(working: Path, rows: list[dict[str, str]]) -> None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.records.messages import NewMessage

    repo = open_data(working, load_data_config()).messages
    for row in rows:
        repo.append(
            NewMessage(
                row.get("from", "sender"),
                row.get("to", "main"),
                row.get("kind", "info"),
                row.get("text", "message"),
                ts="2026-10-22T10:00:00Z",
            )
        )


def test_status_rolls_up_tasks_and_now_lines(tmp_path: Path) -> None:
    working = tmp_path / "working"
    plan = write_artifact(
        working / "plans" / "sample" / "plan.md",
        "type: plan\nid: sample\ntitle: Sample\nstatus: active",
    )
    write_artifact(
        plan.parent / "tasks" / "one.md",
        "type: task\nid: one\ntitle: First\nstatus: done",
    )
    write_artifact(
        plan.parent / "tasks" / "two.md",
        "type: task\nid: two\ntitle: Second\nstatus: todo\ndepends_on: [one]",
    )
    now_path = working / ".cache" / "plan-now" / "sample.txt"
    now_path.parent.mkdir(parents=True)
    now_path.write_text("checking details\n")

    report = status.collect_from(working)

    assert report["plans"][0]["id"] == "sample"
    assert report["plans"][0]["done"] == 1
    assert report["plans"][0]["total"] == 2
    assert report["plans"][0]["now"] == "checking details"
    assert report["plans"][0]["now_at"] is not None


def test_status_now_lines_do_not_collide_for_duplicate_plan_ids(tmp_path: Path) -> None:
    working = tmp_path / "working"
    first = write_artifact(
        working / "plans" / "a" / "same" / "plan.md",
        "type: plan\nid: duplicate\ntitle: First\nstatus: active",
    )
    write_artifact(
        working / "plans" / "b" / "same" / "plan.md",
        "type: plan\nid: duplicate\ntitle: Second\nstatus: active",
    )
    current, _ = now.line_paths(working / "plans", first)
    current.parent.mkdir(parents=True)
    current.write_text("LINE-A\n", encoding="utf-8")

    rows = {row["title"]: row for row in status.collect_from(working)["plans"]}

    assert rows["First"]["now"] == "LINE-A"
    assert rows["Second"]["now"] == "no tasks yet"


def test_status_resolves_plan_labels_and_inherited_groups(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    parent = write_artifact(
        plans / "parent" / "plan.md",
        "type: plan\ntitle: Parent title\nlabel: Parent label\n"
        "group: Quality score\nshape: group\nstatus: active",
    )
    child = write_artifact(
        parent.parent / "child" / "plan.md",
        "type: plan\ntitle: Child title\ngroup: ' '\nshape: group",
    )
    write_artifact(
        child.parent / "grandchild" / "plan.md",
        "type: plan\ntitle: Grandchild title\ngroup: Dashboard",
    )

    def flatten(rows):
        return [row for item in rows for row in [item, *flatten(item["children"])]]

    rows = {row["id"]: row for row in flatten(status.collect_from(tmp_path)["plans"])}

    assert rows["parent"]["label"] == "Parent label"
    assert rows["parent"]["group_name"] == "Quality score"
    assert rows["parent"]["group"] is True
    assert rows["child"]["label"] == "Child title"
    assert rows["child"]["group_name"] == "Quality score"
    assert rows["grandchild"]["group_name"] == "Dashboard"


def test_status_includes_first_problem_sentence_as_purpose(tmp_path: Path) -> None:
    plan = write_artifact(
        tmp_path / "plans" / "sample" / "plan.md",
        "type: plan\ntitle: Sample\nlabel: Fix mobile cards",
        "## Problem\n\nThe cards overflow on narrow screens. A second sentence follows."
        "\n\n## Solution\nDo the work.\n",
    )
    row = status.read_plan(plan, 20)
    assert row is not None
    assert row["purpose"] == "The cards overflow on narrow screens."


def test_status_purpose_truncates_at_word_boundary_with_ellipsis(
    tmp_path: Path,
) -> None:
    purpose = "Readable " + "purpose " * 30 + "."
    plan = write_artifact(
        tmp_path / "plans" / "sample" / "plan.md",
        "type: plan\ntitle: Sample\nlabel: Fix mobile cards",
        f"## Problem\n\n{purpose}\n",
    )

    row = status.read_plan(plan, 20)

    assert row is not None
    assert row["purpose"].endswith("…")
    assert len(row["purpose"]) <= 141
    assert not row["purpose"].removesuffix("…").endswith("purpos")


def test_status_purpose_hard_cuts_unbroken_token(tmp_path: Path) -> None:
    plan = write_artifact(
        tmp_path / "plans" / "sample" / "plan.md",
        "type: plan\ntitle: Sample\nlabel: Fix mobile cards",
        f"## Problem\n\n{'x' * 300}.\n",
    )

    row = status.read_plan(plan, 20)

    assert row is not None
    assert row["purpose"] == "x" * 140 + "…"


def test_status_purpose_is_blank_without_problem_section(tmp_path: Path) -> None:
    plan = write_artifact(
        tmp_path / "plans" / "sample" / "plan.md", "type: plan\ntitle: Sample"
    )
    row = status.read_plan(plan, 20)
    assert row is not None
    assert row["purpose"] == ""


def test_status_falls_back_past_unreadable_parent_and_blank_labels(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "plans"
    grandparent = write_artifact(
        plans / "grandparent" / "plan.md",
        "type: plan\ntitle: Grandparent title\ngroup: Quality score",
    )
    unreadable = grandparent.parent / "parent" / "plan.md"
    unreadable.parent.mkdir()
    unreadable.write_text("---\ntype: plan\nlabel: [invalid\n---\n", encoding="utf-8")
    child = write_artifact(
        unreadable.parent / "child" / "plan.md",
        "type: plan\ntitle: Child title\nlabel: '   '",
    )
    task = write_artifact(
        child.parent / "tasks" / "task.md",
        "type: task\ntitle: Task title\nlabel: ''",
    )

    report = status.collect_from(tmp_path)

    def flatten(rows):
        return [row for item in rows for row in [item, *flatten(item["children"])]]

    rows = {row["id"]: row for row in flatten(report["plans"])}
    assert rows["child"]["label"] == "Child title"
    assert rows["child"]["group_name"] == "Quality score"
    task_row = status.read_plan(task, 60)
    assert task_row is not None
    assert task_row["label"] == "Task title"


def test_status_json_exposes_assignment_and_merge_approval(tmp_path: Path) -> None:
    working = tmp_path / "working"
    write_artifact(
        working / "plans" / "sample" / "plan.md",
        "type: plan\nid: sample\ntitle: Sample\nstatus: active\n"
        "assigned_to: orchestrator-2\nmerge_approved_at: '2026-10-22T10:00:00Z'",
    )

    plan = status.collect_from(working)["plans"][0]

    assert plan["assigned_to"] == "orchestrator-2"
    assert plan["merge_approved_at"] == "2026-10-22T10:00:00Z"
    assert plan["merge_state"] == "unknown"
    assert plan["stalled"] is False


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - test invokes fixed Git operations
        ["git", "-C", str(repo), *args],  # noqa: S607 - fixed Git executable
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_status_classifies_approved_unmerged_and_merged_branches(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "file").write_text("base", encoding="utf-8")
    _git(repo, "add", "file")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "worktree/sample")
    (repo / "file").write_text("branch", encoding="utf-8")
    _git(repo, "commit", "-am", "branch change")
    working = tmp_path / "working"
    write_artifact(
        working / "plans" / "sample" / "plan.md",
        "type: plan\nid: sample\ntitle: Sample\nstatus: active\n"
        "branch: worktree/sample\nmerge_approved_at: '2026-10-22T10:00:00Z'",
    )

    unmerged = status.collect_from(working, repo=repo)["plans"][0]
    assert unmerged["merge_state"] == "approved_not_merged"

    _git(repo, "checkout", "main")
    _git(repo, "merge", "--ff-only", "worktree/sample")

    merged = status.collect_from(working, repo=repo)["plans"][0]
    assert merged["merge_state"] == "merged"


def test_status_fresh_note_suppresses_task_stall(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    plan = write_artifact(
        working / "plans" / "sample" / "plan.md",
        "type: plan\nid: sample\ntitle: Sample\nstatus: active",
    )
    write_artifact(
        plan.parent / "tasks" / "one.md",
        "type: task\nid: one\ntitle: Task\nstatus: building\n"
        "status_at: '1970-01-01T00:00:10+00:00'",
    )
    note = plan.parent / "notes" / "one.md"
    note.parent.mkdir()
    note.write_text("Recent activity", encoding="utf-8")
    task_time = 10_000.0
    note_time = task_time - 30
    import os

    os.utime(note, (note_time, note_time))
    monkeypatch.setattr(status.time, "time", lambda: task_time)

    row = status.collect_from(working, stall_minutes=60)["plans"][0]

    assert row["now"] == "Task building"


def test_task_stat_failure_does_not_drop_task_from_status(
    tmp_path: Path, monkeypatch
) -> None:
    plan = write_artifact(
        tmp_path / "plans" / "sample" / "plan.md",
        "type: plan\nid: sample\nstatus: active",
    )
    task = write_artifact(
        plan.parent / "tasks" / "one.md", "type: task\nid: one\nstatus: todo"
    )
    original_stat = Path.stat
    calls = 0

    def fail_task_stat(self: Path, *args, **kwargs):
        nonlocal calls
        if self == task:
            calls += 1
            if calls == 1:
                raise OSError("simulated stat failure")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_task_stat)

    row = status.read_plan(plan, stall_minutes=60)

    assert row is not None
    assert row["total"] == 1
    assert row["task_now"] == "next: one"


def test_note_stat_failure_keeps_task_and_uses_task_activity(
    tmp_path: Path, monkeypatch
) -> None:
    plan = write_artifact(
        tmp_path / "plans" / "sample" / "plan.md",
        "type: plan\nid: sample\nstatus: active",
    )
    write_artifact(
        plan.parent / "tasks" / "one.md",
        "type: task\nid: one\ntitle: Task\nstatus: building\n"
        "status_at: '1970-01-01T00:00:10+00:00'",
    )
    note = plan.parent / "notes" / "one.md"
    note.parent.mkdir()
    note.write_text("Recent activity", encoding="utf-8")
    original_stat = Path.stat

    def fail_note_stat(self: Path, *args, **kwargs):
        if self == note:
            raise OSError("simulated note stat failure")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_note_stat)
    monkeypatch.setattr(status.time, "time", lambda: 10_000.0)

    row = status.read_plan(plan, stall_minutes=60)

    assert row is not None
    assert row["total"] == 1
    assert row["task_now"].startswith("Task stalled ")


def test_task_active_states_match_data_view() -> None:
    assert frozenset(TASK_ACTIVE) == VIEW_TASK_ACTIVE


def test_status_json_exposes_awaiting_user_reason(tmp_path: Path) -> None:
    working = tmp_path / "working"
    write_artifact(
        working / "plans" / "sample" / "plan.md",
        "type: plan\nid: sample\ntitle: Sample\nstatus: active\n"
        "assigned_to: orchestrator-2",
    )
    _append_messages(
        working,
        [
            {
                "from": "orchestrator-2",
                "to": "main",
                "kind": "needs-user",
                "text": "Approve release",
            }
        ],
    )

    plan = status.collect_from(working)["plans"][0]

    assert plan["awaiting_user"] == "Approve release"


def test_status_does_not_mark_awaiting_plan_stalled(
    tmp_path: Path, monkeypatch
) -> None:
    working = tmp_path / "working"
    plan_path = write_artifact(
        working / "plans" / "sample" / "plan.md",
        "type: plan\nid: sample\ntitle: Sample\nstatus: active\n"
        "assigned_to: orchestrator-2",
    )
    write_artifact(
        plan_path.parent / "tasks" / "open.md",
        "type: task\nid: open\nstatus: todo",
    )
    _append_messages(
        working,
        [
            {
                "from": "orchestrator-2",
                "to": "main",
                "kind": "needs-user",
                "text": "Approve release",
            }
        ],
    )
    monkeypatch.setattr(
        status,
        "read_bindings",
        lambda _working: [
            {"address": "orchestrator-2", "last_seen": "2026-10-22T10:00:00Z"}
        ],
    )

    plan = status.collect_from(working, now=1_792_667_200.0)["plans"][0]

    assert plan["awaiting_user"] == "Approve release"
    assert plan["stalled"] is False


def test_status_json_marks_merge_state_absent_without_approval(tmp_path: Path) -> None:
    working = tmp_path / "working"
    write_artifact(
        working / "plans" / "sample" / "plan.md",
        "type: plan\nid: sample\ntitle: Sample\nstatus: active",
    )

    plan = status.collect_from(working)["plans"][0]

    assert plan["merge_state"] == "absent"
    assert plan["stalled"] is False


def test_status_reads_legacy_now_line(tmp_path: Path) -> None:
    working = tmp_path / "working"
    write_artifact(
        working / "plans" / "sample" / "plan.md",
        "type: plan\nid: sample\ntitle: Sample\nstatus: active",
    )
    (working / "plan-now").mkdir()
    (working / "plan-now" / "sample.txt").write_text("legacy progress\n")

    report = status.collect_from(working)

    assert report["plans"][0]["now"] == "legacy progress"


def test_readiness_adds_both_readiness_fields(tmp_path: Path, capsys) -> None:
    plan = write_artifact(
        tmp_path / "plan.md", "type: plan\nid: sample\nstatus: active"
    )

    code = readiness.run(SimpleNamespace(plan=plan, json=True))

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["planning_ready"] is True
    assert payload["data"]["implementation_ready"] is True


def test_now_normalizes_and_reads_progress_line(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo = tmp_path / "repo"
    plan = write_artifact(
        repo / "working" / "plans" / "sample" / "plan.md",
        "type: plan\nid: sample\nstatus: active",
    )
    monkeypatch.chdir(repo)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(repo / "working"))

    code = now.run(
        SimpleNamespace(
            plan="sample",
            clear=False,
            waiting=None,
            text="  details\n  here ",
            json=True,
        )
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["data"]["now"] == "details here"
    assert now.read_line(plan.parents[1], plan) == "details here"
    assert (plan.parents[2] / ".cache" / "plan-now" / "sample.txt").exists()


def test_now_json_uses_sorted_cli_envelope(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = tmp_path / "repo"
    write_artifact(
        repo / "working" / "plans" / "sample" / "plan.md",
        "type: plan\nid: sample\nstatus: active",
    )
    monkeypatch.chdir(repo)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(repo / "working"))

    code = now.run(
        SimpleNamespace(
            plan="sample", clear=False, waiting=None, text="details", json=True
        )
    )

    assert code == 0
    assert capsys.readouterr().out.startswith(
        '{"data":{"now":"details","plan":"sample"}'
    )


def test_now_clear_removes_legacy_line(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = tmp_path / "repo"
    plan = write_artifact(
        repo / "working" / "plans" / "sample" / "plan.md",
        "type: plan\nid: sample\nstatus: active",
    )
    legacy_path = plan.parents[2] / "plan-now" / "sample.txt"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text("old line\n")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(repo / "working"))

    code = now.run(
        SimpleNamespace(plan="sample", clear=True, waiting=None, text=None, json=True)
    )

    assert code == 0
    assert not legacy_path.exists()
    assert now.read_line(plan.parents[1], plan) is None


def test_status_json_uses_sorted_cli_envelope(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    code = status.run(SimpleNamespace(json=True, repo=None))

    assert code == 0
    assert capsys.readouterr().out.startswith(
        '{"data":{"backlog_count":0,"more_count":0,"open_comments":0,"plans":[],"skipped":0}'
    )


def test_status_shows_waiting_on_cancelled_dependency(tmp_path: Path) -> None:
    working = tmp_path / "working"
    plans = working / "plans"
    write_artifact(
        plans / "parent" / "plan.md",
        "type: plan\nid: parent\ntitle: Parent\nstatus: active\n"
        "depends_on: [cancelled]",
    )
    write_artifact(
        plans / "cancelled" / "plan.md",
        "type: plan\nid: cancelled\ntitle: Cancelled\nstatus: cancelled",
    )

    report = status.collect_from(working)

    assert next(item for item in report["plans"] if item["id"] == "parent")["now"] == (
        "waits on cancelled"
    )


def test_status_reads_message_log_once_for_all_assigned_plans(
    tmp_path: Path, monkeypatch
) -> None:
    from varde_workflow import merge_state

    working = tmp_path / "working"
    for name in ("a", "b", "c"):
        write_artifact(
            working / "plans" / name / "plan.md",
            f"type: plan\nid: {name}\ntitle: {name}\nstatus: active\n"
            "assigned_to: orchestrator-2",
        )
    reads: list[Path] = []
    real = merge_state.read_messages
    monkeypatch.setattr(
        merge_state, "read_messages", lambda path: reads.append(path) or real(path)
    )
    monkeypatch.setattr(status, "read_messages", merge_state.read_messages)

    status.collect_from(working)

    assert len(reads) == 1


def test_local_branches_lists_branch_names_and_feeds_merge_state(
    tmp_path: Path,
) -> None:
    from varde_workflow import merge_state

    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ["init", "-q", "-b", "main"],
        [
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        ],
        ["branch", "worktree/plan-a"],
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True)  # noqa: S603, S607

    branches = merge_state.local_branches(repo)
    record = {"id": "plan-a", "merge_approved_at": "2026-10-22T10:00:00Z"}

    assert branches == {"main", "worktree/plan-a"}
    assert merge_state.json_merge_state(
        record, repo, branches
    ) == merge_state.json_merge_state(record, repo)
    assert merge_state.local_branches(tmp_path / "missing") == frozenset()


def test_staleness_counts_nested_commit_for_trailing_slash_owns(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "src" / "pkg" / "a.py").write_text("1")

    def run(*args: str) -> str:
        return subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(repo),
                "-c",
                "user.email=t@e.com",
                "-c",
                "user.name=T",
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    subprocess.run(["git", "init", "-q", str(repo)], check=True)  # noqa: S603, S607
    run("add", ".")
    run("commit", "-qm", "base")
    base = run("rev-parse", "HEAD")
    (repo / "src" / "pkg" / "a.py").write_text("2")
    run("commit", "-qam", "touch")
    plan = write_artifact(
        tmp_path / "plans" / "p" / "plan.md",
        f"type: plan\nstatus: in_progress\nreviewed_commit: {base}\n"
        "reviewed_on: 2026-10-30",
    )
    write_artifact(
        plan.parent / "tasks" / "t.md",
        "type: task\nstatus: todo\nowns: [src/pkg/]",
    )
    notice = status.staleness_notice_for(plan, repo)
    assert notice is not None and "1 commits since" in notice
