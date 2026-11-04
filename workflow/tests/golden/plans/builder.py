from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

FIXED_MTIME = 1_700_000_000
FIXED_CLOCK = 1_700_000_100
ASSIGNED_PLAN_MTIME = 1_700_000_010
ASSIGNED_TASK_MTIME = 1_700_000_020
ASSIGNED_STATUS_AT = 1_700_000_030
ASSIGNED_COMMIT_AT = 1_700_000_040
SNAPSHOTS = Path(__file__).parent


def build(root: Path) -> tuple[Path, Path]:
    time.tzset()
    working = root / "working"
    status_at = datetime.fromtimestamp(ASSIGNED_STATUS_AT, UTC).isoformat().replace(
        "+00:00", "Z"
    )
    cases = {
        "group/nested": "type: plan\nid: nested\ntitle: Nested\nstatus: active",
        "same-a/duplicate": "type: plan\nid: duplicate-a\ntitle: Duplicate A\nstatus: active",
        "same-b/duplicate": "type: plan\nid: duplicate-b\ntitle: Duplicate B\nstatus: active",
        "2026-10-23-date-suffix": "type: plan\nid: date-suffix\ntitle: Date suffix\nstatus: backlog",
        "archive/old": "type: plan\nid: old\ntitle: Archived\nstatus: active",
        "assigned/plan": (
            "type: plan\nid: assigned\ntitle: Assigned plan\nstatus: active\n"
            "assigned_to: agent-1\nbranch: worktree/assigned"
        ),
    }
    for directory, frontmatter in cases.items():
        plan = working / "plans" / directory / "plan.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(f"---\n{frontmatter}\n---\n", encoding="utf-8")
        os.utime(plan, (FIXED_MTIME, FIXED_MTIME))
    for relative, contents in {
        "group/nested/tasks/task.md": "---\ntype: task\nid: task\ntitle: Task\nstatus: todo\n---\n",
        "group/nested/tasks/bad.md": "---\ntype: task\nid: [broken\n---\n",
        "assigned/plan/tasks/active.md": (
            "---\ntype: task\nid: active\ntitle: Active task\n"
            f"status: in_progress\nstatus_at: '{status_at}'\n---\n"
        ),
        "group/bad/plan.md": "---\ntype: plan\nid: [broken\n---\n",
    }.items():
        path = working / "plans" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        os.utime(path, (FIXED_MTIME, FIXED_MTIME))
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)  # noqa: S603, S607
    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Golden Test",
        "GIT_AUTHOR_EMAIL": "golden@example.test",
        "GIT_COMMITTER_NAME": "Golden Test",
        "GIT_COMMITTER_EMAIL": "golden@example.test",
        "GIT_AUTHOR_DATE": "@1699999900 +0000",
        "GIT_COMMITTER_DATE": "@1699999900 +0000",
    }
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "checkout", "-q", "-b", "main"],  # noqa: S607
        check=True,
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "checkout", "-q", "-b", "feature"],  # noqa: S607
        check=True,
    )
    (repo / "README.md").write_text("golden repo\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "README.md"], env=git_env, check=True
    )  # noqa: S603
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "initial"],
        env=git_env,
        check=True,
    )  # noqa: S603
    subprocess.run(
        ["git", "-C", str(repo), "branch", "-f", "main", "HEAD"],
        env=git_env,
        check=True,
    )  # noqa: S603
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-q", "main"], env=git_env, check=True
    )  # noqa: S603
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-q", "-b", "worktree/assigned"],
        env=git_env,
        check=True,
    )  # noqa: S603
    (repo / "README.md").write_text("assigned branch\n", encoding="utf-8")
    git_env["GIT_AUTHOR_DATE"] = f"@{ASSIGNED_COMMIT_AT} +0000"
    git_env["GIT_COMMITTER_DATE"] = f"@{ASSIGNED_COMMIT_AT} +0000"
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-a", "-q", "-m", "assigned work"],
        env=git_env,
        check=True,
    )  # noqa: S603
    os.utime(
        working / "plans/assigned/plan/plan.md",
        (ASSIGNED_PLAN_MTIME, ASSIGNED_PLAN_MTIME),
    )
    os.utime(
        working / "plans/assigned/plan/tasks/active.md",
        (ASSIGNED_TASK_MTIME, ASSIGNED_TASK_MTIME),
    )
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-q", "main"], env=git_env, check=True
    )  # noqa: S603
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "worktree",
            "add",
            "-q",
            str(root / "worktree"),
            "worktree/assigned",
        ],
        env=git_env,
        check=True,
    )  # noqa: S603
    from varde_workflow.binding import BindingStore

    now = datetime.fromtimestamp(FIXED_CLOCK, UTC)
    store = BindingStore(working)
    marker = store.issue("agent-1", now=now)
    assert store.redeem(marker, "golden-agent", "codex", str(repo), now=now)
    inbox = working / ".cache/inbox/messages.jsonl"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    inbox.write_text(
        json.dumps(
            {
                "ts": "2023-11-14T22:15:00Z",
                "from": "agent-1",
                "to": "main",
                "kind": "needs-user",
                "text": "Please approve the assigned plan.",
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return working, repo


def check_snapshot(name: str, stdout: str, root: Path) -> None:
    normalized = stdout.replace(str(root), "<TMP>")
    path = SNAPSHOTS / f"{name}.json"
    if os.environ.get("VARDE_UPDATE_GOLDENS") == "1":
        print(f"updated golden: {path}")
        path.write_text(normalized, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == normalized
