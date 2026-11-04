from pathlib import Path

import pytest
from varde_workflow.commands.merge_gate import (
    plan_branches,
    plans_brought_in,
    revision_matches_plan,
)


@pytest.fixture(autouse=True)
def runner_on(monkeypatch) -> None:
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "1")


BRANCHES = [("p1", "feature/renamed"), ("p2", "worktree/p2"), ("p3", "worktree/p3")]
TIPS = {"feature/renamed": "t1", "worktree/p2": "t2"}
# commit -> commits that contain it
CONTAINED_IN = {"c1": {"t1", "c1"}, "c2": {"t2", "c2"}, "main1": {"HEAD", "t1", "t2"}}


def reachable(commit: str, tip: str) -> bool:
    return tip in CONTAINED_IN.get(commit, set())


def brought_in(*commits: str) -> list[str]:
    return plans_brought_in(commits, BRANCHES, TIPS.get, reachable, "HEAD")


def test_a_renamed_branch_or_a_commit_inside_it_is_matched_by_content() -> None:
    assert brought_in("t1") == []  # unknown commit: nothing reachable
    assert brought_in("c1") == ["p1"]


def test_commits_already_on_head_and_branchless_plans_are_ignored() -> None:
    assert brought_in("main1") == []
    assert brought_in() == []


def test_an_octopus_merge_lists_every_plan_it_carries() -> None:
    assert brought_in("c1", "c2") == ["p1", "p2"]


def test_plan_branches_read_frontmatter_ids_and_branches(tmp_path: Path) -> None:
    plan = tmp_path / "plans" / "x" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\nid: x\nbranch: feature/renamed\n---\nbody\n")
    (tmp_path / "plans" / "y").mkdir()
    (tmp_path / "plans" / "y" / "plan.md").write_text("---\nid: y\n---\n")
    assert plan_branches(tmp_path / "plans") == [
        ("x", "feature/renamed"),
        ("y", "worktree/y"),
    ]


def test_registered_task_branch_and_default_worktree_branch_match(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "plans"
    plans.mkdir()
    task_plan = plans / "role-inbox" / "plan.md"
    task_plan.parent.mkdir()
    task_plan.write_text("---\nid: role-inbox\nbranches:\n  - role-inbox-t05\n---\n")
    default_plan = plans / "ux-fixes-round4" / "plan.md"
    default_plan.parent.mkdir()
    default_plan.write_text("---\nid: ux-fixes-round4\n---\n")
    assert plan_branches(plans) == [
        ("role-inbox", "worktree/role-inbox"),
        ("role-inbox", "role-inbox-t05"),
        ("ux-fixes-round4", "worktree/ux-fixes-round4"),
    ]
    tips = {"role-inbox-t05": "task-tip", "worktree/ux-fixes-round4": "ux-tip"}
    ancestry = {"task-tip": {"task-tip"}, "ux-tip": {"ux-tip"}}

    def is_reachable(commit: str, tip: str) -> bool:
        return tip in ancestry.get(commit, set())

    assert revision_matches_plan("task-tip", "role-inbox-t05", tips.get, is_reachable)
    assert revision_matches_plan(
        "ux-tip", "worktree/ux-fixes-round4", tips.get, is_reachable
    )


def test_unmatched_task_branch_fails_closed_with_revision(
    monkeypatch, tmp_path, capsys
) -> None:
    from types import SimpleNamespace

    from varde_workflow import merge_approval
    from varde_workflow.commands import merge_gate

    plans = tmp_path / "plans"
    plans.mkdir()
    monkeypatch.setattr(merge_gate.Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        merge_gate.MemoryPaths,
        "resolve",
        lambda _cwd: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    monkeypatch.setattr(
        merge_gate,
        "resolve_commit",
        lambda _cwd, rev: "commit" if rev == "role-inbox-t05" else "head",
    )
    monkeypatch.setattr(
        merge_gate,
        "is_ancestor",
        lambda _cwd, ancestor, descendant: ancestor == descendant,
    )
    monkeypatch.setattr(merge_approval, "fetch_approval", lambda _key, _reviewed: None)
    assert merge_gate.run(SimpleNamespace(revs=["role-inbox-t05"])) == 1
    assert "revision role-inbox-t05" in capsys.readouterr().err


def test_complete_main_approval_is_accepted_for_reviewed_plan(
    monkeypatch, tmp_path
) -> None:
    from types import SimpleNamespace

    from varde_workflow import merge_approval
    from varde_workflow.commands import merge_gate

    plan = tmp_path / "plans" / "p1" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\nid: p1\nreviewed_commit: review-sha\n---\n", encoding="utf-8")
    monkeypatch.setattr(merge_gate.Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        merge_gate.MemoryPaths,
        "resolve",
        lambda _cwd: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    monkeypatch.setattr(
        merge_gate,
        "resolve_commit",
        lambda _cwd, rev: {
            "feature": "merge-sha",
            "HEAD": "head",
            "refs/heads/worktree/p1": "tip",
            "review-sha": "review-sha",
        }.get(rev),
    )
    monkeypatch.setattr(
        merge_gate,
        "is_ancestor",
        lambda _cwd, ancestor, descendant: (
            (ancestor, descendant)
            in {
                ("merge-sha", "tip"),
                ("tip", "merge-sha"),
                ("tip", "review-sha"),
            }
        ),
    )

    checklist = {
        "plan_followed": True,
        "review_commit": "review-sha",
        "gate_result": "pass",
        "abnormal_events": "none",
    }
    record = {
        "plan_id": "p1",
        "approved_by": "main",
        "approver_kind": "main",
        "approved_at": "2026-01-01",
        "commit_sha": "review-sha",
        "checklist": checklist,
    }

    def fetch(_key, reviewed_commit):
        return merge_approval.parse_approval({"approval": record}, reviewed_commit)

    monkeypatch.setattr(merge_approval, "fetch_approval", fetch)
    monkeypatch.setattr(
        merge_gate,
        "plan_branches",
        lambda _plans: [("p1", "worktree/p1")],
    )
    assert merge_gate.run(SimpleNamespace(revs=["feature"])) == 0


def test_plan_branch_registration_preserves_frontmatter_and_body() -> None:
    from varde_workflow.commands.owner import set_branches_line

    original = b"---\nid: p1\nbranch: worktree/p1\n---\nbody\n"
    first = set_branches_line(original, "task/t01")
    second = set_branches_line(first, "task/t01")
    assert b"branches:\n  - task/t01\n" in second
    assert second.endswith(b"---\nbody\n")
    assert second.count(b"task/t01") == 1


@pytest.mark.parametrize("branch", ["main", "old", "missing"])
def test_register_branch_rejects_main_ancestors_and_missing_refs(
    tmp_path: Path, monkeypatch, branch: str, capsys
) -> None:
    import subprocess
    from types import SimpleNamespace

    from varde_workflow.commands import owner

    def git(*args: str) -> str:
        done = subprocess.run(  # noqa: S603 - fixed git argv for temporary repo.
            [  # noqa: S607 - git is resolved from PATH.
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return done.stdout.strip()

    git("init", "-q", "-b", "main")
    git("commit", "--allow-empty", "-qm", "base")
    git("branch", "old")
    plan = tmp_path / "plans" / "p1" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\nid: p1\n---\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        owner.MemoryPaths,
        "resolve",
        lambda _cwd: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    before = plan.read_bytes()
    assert owner.register_branch(SimpleNamespace(plan="p1/plan.md", branch=branch)) == 1
    assert plan.read_bytes() == before
    assert capsys.readouterr().err


def test_real_git_matches_a_renamed_branch_and_a_bare_commit_id(tmp_path: Path) -> None:
    import subprocess

    from varde_workflow.commands.merge_gate import is_ancestor, resolve_commit

    def git(*args: str) -> str:
        done = subprocess.run(  # noqa: S603 - fixed argv in a temp repo.
            [  # noqa: S607 - git from PATH.
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return done.stdout.strip()

    git("init", "-q", "-b", "main")
    git("commit", "--allow-empty", "-qm", "base")
    git("switch", "-qc", "feature/renamed")
    git("commit", "--allow-empty", "-qm", "plan work")
    first = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-qm", "more")
    git("switch", "-q", "main")
    head = resolve_commit(tmp_path, "HEAD") or ""
    for rev in ("feature/renamed", first):
        found = plans_brought_in(
            [resolve_commit(tmp_path, rev) or ""],
            [("p1", "feature/renamed"), ("p2", "worktree/p2")],
            lambda branch: resolve_commit(tmp_path, f"refs/heads/{branch}"),
            lambda a, b: is_ancestor(tmp_path, a, b),
            head,
        )
        assert found == ["p1"], rev


def test_real_git_old_plan_ancestor_does_not_claim_unowned_task_branch(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    import subprocess
    from types import SimpleNamespace

    from varde_workflow import merge_approval
    from varde_workflow.commands import merge_gate

    def git(*args: str) -> str:
        done = subprocess.run(  # noqa: S603 - fixed git argv for temporary repo.
            [  # noqa: S607 - git is resolved from PATH.
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return done.stdout.strip()

    git("init", "-q", "-b", "main")
    git("commit", "--allow-empty", "-qm", "base")
    git("switch", "-qc", "worktree/old-plan")
    git("commit", "--allow-empty", "-qm", "old plan")
    old_tip = git("rev-parse", "HEAD")
    git("switch", "-q", "main")
    git("switch", "-qc", "task/round4-like")
    git("commit", "--allow-empty", "-qm", "unowned task")
    task_tip = git("rev-parse", "HEAD")
    git("switch", "-q", "main")

    plans = tmp_path / "plans" / "old-plan"
    plans.mkdir(parents=True)
    (plans / "plan.md").write_text(
        "---\nid: old-plan\nbranch: worktree/old-plan\n---\n"
    )
    monkeypatch.setattr(merge_gate.Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        merge_gate.MemoryPaths,
        "resolve",
        lambda _cwd: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    monkeypatch.setattr(merge_approval, "fetch_approval", lambda _key, _reviewed: None)
    assert old_tip != task_tip
    assert merge_gate.run(SimpleNamespace(revs=["task/round4-like"], mode="merge")) == 1
    assert "revision task/round4-like" in capsys.readouterr().err
    assert merge_gate.run(SimpleNamespace(revs=[task_tip], mode="backstop")) == 1


@pytest.mark.parametrize("revs", [[], ["missing-rev"]])
def test_empty_or_unresolvable_revisions_fail_closed(
    tmp_path, monkeypatch, capsys, revs
):
    from types import SimpleNamespace

    from varde_workflow.commands import merge_gate

    monkeypatch.setattr(merge_gate.Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        merge_gate.MemoryPaths,
        "resolve",
        lambda _cwd: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    assert merge_gate.run(SimpleNamespace(revs=revs, mode="merge")) == 1
    assert capsys.readouterr().err


@pytest.mark.parametrize("mode", ["merge", "backstop"])
@pytest.mark.parametrize("value", ["0", ""])
def test_runner_off_skips_the_gate_with_a_note(
    tmp_path, monkeypatch, capsys, mode, value
):
    from types import SimpleNamespace

    from varde_workflow import merge_approval
    from varde_workflow.commands import merge_gate

    monkeypatch.setenv("VARDE_RUNNER_ENABLED", value)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        merge_approval,
        "fetch_approval",
        lambda *_: pytest.fail("fetch_approval called with runner off"),
    )
    monkeypatch.setattr(
        merge_gate.MemoryPaths,
        "resolve",
        lambda _cwd: pytest.fail("memory resolved with runner off"),
    )
    assert merge_gate.run(SimpleNamespace(revs=["anything"], mode=mode)) == 0
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert "runner disabled; merge approval check skipped" in err


@pytest.mark.parametrize("mode", ["merge", "backstop"])
def test_real_git_unowned_revision_is_blocked_only_with_the_runner_on(
    tmp_path: Path, monkeypatch, mode
) -> None:
    import subprocess
    from types import SimpleNamespace

    from varde_workflow import merge_approval
    from varde_workflow.commands import merge_gate

    def git(*args: str) -> str:
        return subprocess.run(  # noqa: S603 - fixed git argv for temporary repo.
            [  # noqa: S607 - git from PATH.
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    git("commit", "--allow-empty", "-qm", "base")
    git("switch", "-qc", "task/unowned")
    git("commit", "--allow-empty", "-qm", "unowned task")
    tip = git("rev-parse", "HEAD")
    git("switch", "-q", "main")
    (tmp_path / "plans").mkdir()
    monkeypatch.setattr(merge_gate.Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        merge_gate.MemoryPaths,
        "resolve",
        lambda _cwd: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    monkeypatch.setattr(merge_approval, "fetch_approval", lambda _key, _reviewed: None)
    args = SimpleNamespace(revs=[tip], mode=mode)
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "1")
    assert merge_gate.run(args) == 1
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "0")
    assert merge_gate.run(args) == 0
