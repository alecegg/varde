"""Who may apply a proposal: the user's recorded answer and the allowed paths.

`accept` applies only a proposal whose latest decision row on a report page is
an approval, and only to skill or agent source inside the given roots. The
checks are pure apart from reading the comment logs.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from varde_learn.docs.pages import comments

from . import record as rec

APPROVED = "approved"  # the verdict the page stores for the `approve` option
SOURCE_DIRS = ("skills", "how", "agents", "step_tools")


def report_dir(memory_root: Path) -> Path:
    return rec.loop_dir(memory_root) / "report"


def report_pages(memory_root: Path) -> list[Path]:
    base = report_dir(memory_root)
    return sorted(base.glob("*.md")) if base.is_dir() else []


def latest_verdict(memory_root: Path, record_id: str) -> str | None:
    """Verdict of the newest decision row for `record_id` across report pages."""
    verdict = None
    for page in report_pages(memory_root):
        for row in comments.read_rows(page):
            if row.get("kind") == "decision" and row.get("item") == record_id:
                verdict = str(row.get("verdict", ""))
    return verdict


def page_for(memory_root: Path, record_id: str) -> Path | None:
    """The newest report page holding the proposal's decision statement."""
    marker = re.compile(rf"ui id={re.escape(record_id)}(?![\w-])")
    holding = [p for p in report_pages(memory_root) if marker.search(rec.read_raw(p))]
    return holding[-1] if holding else None


def approval_problem(memory_root: Path, record_id: str) -> str | None:
    """Why `record_id` may not be applied yet, or None when the user approved."""
    verdict = latest_verdict(memory_root, record_id)
    if verdict == APPROVED:
        return None
    page = page_for(memory_root, record_id)
    where = (
        f"answer the block on {page}"
        if page
        else "run `varde learn skills report` and answer the block on its page"
    )
    if verdict is None:
        return f"{record_id} has no recorded approval; {where}"
    return f"latest decision for {record_id} is '{verdict}', not approved; {where}"


def outside_roots(paths: Iterable[str], roots: Iterable[Path]) -> list[str]:
    """Paths that are not skill or agent source files inside one of `roots`.

    Paths must be absolute without `..`; symlinks are resolved before checking.
    """
    real_roots = [root.resolve() for root in roots]
    return sorted(path for path in paths if not _inside(path, real_roots))


def _inside(path: str, real_roots: list[Path]) -> bool:
    candidate = Path(path)
    if not candidate.is_absolute() or ".." in candidate.parts:
        return False
    target = candidate.resolve()
    return any(_source_under(target, root) for root in real_roots)


def _source_under(target: Path, root: Path) -> bool:
    if not target.is_relative_to(root):
        return False
    parts = target.relative_to(root).parts
    return len(parts) > 1 and parts[0] in SOURCE_DIRS
