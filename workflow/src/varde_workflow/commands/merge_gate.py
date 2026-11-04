"""Pre-merge gate: each plan a merge brings in needs a valid approval."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from varde_core.frontmatter import parse
from varde_data.config import runner_enabled
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.commands.error import CliError, report_cli_error
from varde_workflow.merge_approval import (
    ApprovalUnavailable,
    plan_identity,
    require_approval,
)

FULL_OBJECT_ID_LENGTH = 40


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed git argv.
        ["git", "-C", str(cwd), *args],  # noqa: S607 - git from PATH.
        check=False,
        capture_output=True,
        text=True,
    )


def resolve_commit(cwd: Path, rev: str) -> str | None:
    result = _git(cwd, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return result.stdout.strip() if result.returncode == 0 else None


def is_ancestor(cwd: Path, ancestor: str, descendant: str) -> bool:
    return (
        _git(cwd, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0
    )


def plan_branches(plans: Path) -> list[tuple[str, str]]:
    """(plan id, branch) for every plan file, from its frontmatter."""
    found: list[tuple[str, str]] = []
    for plan in sorted(plans.glob("*/plan.md")):
        try:
            metadata, _ = parse(plan.read_bytes())
            identifier, branch = plan_identity(metadata, plan.parent.name)
            extra = metadata.get("branches", [])
            if not isinstance(extra, list) or any(
                not isinstance(x, str) or not x for x in extra
            ):
                continue
            found.extend((identifier, item) for item in [branch, *extra])
        except OSError, ValueError:
            continue
    return found


def plan_reviewed_commits(plans: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for plan in sorted(plans.glob("*/plan.md")):
        try:
            metadata, _ = parse(plan.read_bytes())
            identifier, _ = plan_identity(metadata, plan.parent.name)
            reviewed = metadata.get("reviewed_commit")
            if isinstance(reviewed, str) and reviewed.strip():
                result[identifier] = reviewed
        except OSError, ValueError:
            continue
    return result


def plans_brought_in(
    commits: Iterable[str],
    branches: Iterable[tuple[str, str]],
    tip_of: Callable[[str], str | None],
    reachable: Callable[[str, str], bool],
    head: str,
) -> list[str]:
    """Plan ids whose branch holds a merged commit that `head` does not yet have."""
    new_commits = [commit for commit in commits if not reachable(commit, head)]
    return [
        plan_id
        for plan_id, branch in branches
        if (tip := tip_of(branch)) is not None
        and any(reachable(commit, tip) for commit in new_commits)
    ]


def revision_matches_plan(
    revision: str,
    branch: str,
    tip_of: Callable[[str], str | None],
    reachable: Callable[[str, str], bool],
) -> bool:
    """Match only when a registered branch tip contains the revision."""
    tip = tip_of(branch)
    return tip is not None and reachable(revision, tip)


def unowned_revisions(
    revisions: Iterable[tuple[str, str]],
    head: str,
    branches: Iterable[str],
    tip_of: Callable[[str], str | None],
    reachable: Callable[[str, str], bool],
) -> list[tuple[str, str]]:
    """Return revisions new to head and not contained by registered branches."""
    return [
        (rev, commit)
        for rev, commit in revisions
        if (not head or not reachable(commit, head))
        and not any(
            revision_matches_plan(commit, branch, tip_of, reachable)
            for branch in branches
        )
    ]


def run(args: Any) -> int:
    """Exit 1 when a merge of `args.revs` would bring in an unapproved plan."""
    if not runner_enabled():
        print("runner disabled; merge approval check skipped", file=sys.stderr)
        return 0
    cwd = Path.cwd()
    try:
        plans = MemoryPaths.resolve(cwd).working.path / "plans"
        head = (
            ""
            if getattr(args, "mode", "merge") == "backstop"
            else (resolve_commit(cwd, "HEAD") or "")
        )
        if not args.revs:
            raise CliError("merge-gate requires at least one revision")  # noqa: TRY301
        resolved = []
        for rev in args.revs:
            if rev.startswith("-"):
                continue
            commit = resolve_commit(cwd, rev)
            if commit is None:
                raise CliError(f"revision {rev} cannot be resolved to a commit")  # noqa: TRY301
            resolved.append((rev, commit))
        if not resolved:
            raise CliError("merge-gate requires at least one resolvable revision")  # noqa: TRY301
        commits = [commit for _, commit in resolved]
        branches = plan_branches(plans)
        reviewed_commits = plan_reviewed_commits(plans)

        def tip_of(branch: str) -> str | None:
            return resolve_commit(cwd, f"refs/heads/{branch}")

        def reachable(ancestor: str, descendant: str) -> bool:
            return is_ancestor(cwd, ancestor, descendant)

        involved = plans_brought_in(
            commits,
            branches,
            tip_of,
            reachable,
            head,
        )
        for plan_id in involved:
            reviewed = reviewed_commits.get(plan_id, "")
            approval = require_approval(plan_id, reviewed)
            if approval.approver_kind in {"main", "guard"}:
                carrying_tips = [
                    tip
                    for item_id, branch in branches
                    if item_id == plan_id
                    and (tip := tip_of(branch)) is not None
                    and any(reachable(commit, tip) for commit in commits)
                ]
                if not carrying_tips or any(
                    not reachable(tip, reviewed) for tip in carrying_tips
                ):
                    raise CliError(  # noqa: TRY301
                        f"plan {plan_id} branch contains commits beyond reviewed_commit"
                    )
        registered = {branch for _, branch in branches}
        for rev, commit in unowned_revisions(
            resolved, head, registered, tip_of, reachable
        ):
            branch = rev.removeprefix("refs/heads/")
            if branch.startswith("refs/") or len(branch) == FULL_OBJECT_ID_LENGTH:
                branch = f"unknown-{commit[:12]}"
            key = f"branch:{branch}"
            try:
                approval = require_approval(key, "")
            except CliError as exc:
                raise CliError(
                    f"revision {rev} is not associated with a plan and has no user "
                    f"approval for {key}; record approval in the dashboard Mailbox "
                    f"(POST /api/plans/{key}/merge-approval)"
                ) from exc
            if not approval.commit_sha or not reachable(commit, approval.commit_sha):
                raise CliError(  # noqa: TRY301
                    f"approval for {key} does not cover revision {rev}"
                )
    except (ApprovalUnavailable, CliError, OSError, ValueError) as exc:
        error = exc if isinstance(exc, CliError) else CliError(str(exc))
        return report_cli_error(error, json=False)
    return 0
