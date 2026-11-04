"""Pure orphan decision selection for plan watch."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path


def orphan_decisions(
    plans: Iterable[tuple[Path, str]],
    files: Iterable[tuple[Path, Path, bool, float]],
    message_notes: Iterable[str],
    now: float,
) -> list[Path]:
    """Select recent, unreferenced approval files belonging to live plans."""
    live_plan_dirs = {
        _normalized_path(path.parent) for path, bucket in plans if bucket != "terminal"
    }
    referenced = {
        _normalized_path(Path(notes))
        for notes in message_notes
        if Path(notes).is_absolute()
    }
    cutoff = now - 2 * 24 * 60 * 60
    result = []
    for plan_path, path, is_approval, modified in files:
        if _normalized_path(plan_path) not in live_plan_dirs or not is_approval:
            continue
        if modified < cutoff or modified > now:
            continue
        if _normalized_path(path) in referenced:
            continue
        result.append(path)
    return sorted(result)


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))
