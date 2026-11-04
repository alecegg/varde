"""SessionStart `loop_nudge` provider: one free line when loop proposals wait."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from varde_learn.loop.improve.record import LoopRecord


def nudge_line(skill_count: int) -> str:
    """The one-line nudge, or an empty string when no skill has a proposal."""
    if skill_count <= 0:
        return ""
    who = "1 skill has" if skill_count == 1 else f"{skill_count} skills have"
    return f"{who} proposals ready; run `varde learn skills candidates`"


def skills_with_open_proposals(records: Iterable[LoopRecord]) -> int:
    """Distinct skills among records whose state is `proposed` (pure)."""
    return len({r.skill for r in records if r.state == "proposed"})


def loop_nudge_section(cwd: Path) -> str:
    """File scan of the memory root `loop/`; no model call, no network."""
    from varde_learn.loop.improve import record
    from varde_learn.memory import store

    records = record.list_records(store.memory_root(cwd))
    return nudge_line(skills_with_open_proposals(records))
