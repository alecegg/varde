"""changedSince scoping: limit floor and cap findings to files changed since a ref.

The scope mean covers the whole scope, so ``quality-scope-mean`` is never
filtered. Nothing here changes the fast index.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from varde_code.git import run_git
from varde_code.rules.finding import Finding

CHANGE_LIMITED_RULE_IDS = frozenset({"quality-file-floor", "quality-function-cap"})


def parse_changed_paths(diff_output: str) -> frozenset[str]:
    """Split NUL-separated (``-z``) git path output; names are never quoted."""
    return frozenset(name for name in diff_output.split("\0") if name)


def read_changed_paths(root: Path, ref: str) -> frozenset[str] | None:
    """Return root-relative paths changed since ``ref``; None when git fails.

    ``--relative`` keeps paths root-relative when the scan root is a subfolder.
    Untracked, non-ignored files count as changed so new files cannot escape.
    """
    commit = run_git(
        ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"],
        root,
    )
    if commit is None:
        return None
    tracked = run_git(
        ["diff", "-z", "--name-only", "--relative", commit.strip(), "--"], root
    )
    untracked = run_git(["ls-files", "-z", "--others", "--exclude-standard"], root)
    if tracked is None or untracked is None:
        return None
    return parse_changed_paths(tracked) | parse_changed_paths(untracked)


def limit_to_changed(
    findings: Iterable[Finding], changed: frozenset[str]
) -> list[Finding]:
    """Drop floor and cap findings of unchanged files; an empty scope drops all."""
    return [
        f
        for f in findings
        if f.rule_id not in CHANGE_LIMITED_RULE_IDS or f.location.file in changed
    ]
