"""Detect step-tool scripts read or run without the counting wrapper (pure).

The wrapper command never contains the script path, so any session tool call
whose input mentions `step_tools/<skill>/<step>.py` skipped the wrapper.
Report only; nothing is blocked.

Limit: adapters keep only the first 1024 characters of a tool call input
(`tool_input_excerpt`), so a script path that appears after that cut is missed;
the full input is not kept in session records, so this cannot be closed here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from varde_learn.loop.improve.tool_entry import (
    ToolRow,
    all_rows,
    module_roots,
    script_suffix,
)


@dataclass(frozen=True)
class Bypass:
    skill: str
    step: str
    session: str

    def as_dict(self) -> dict[str, str]:
        return {"skill": self.skill, "step": self.step, "session": self.session}


def _input_text(record: Any) -> str:
    getter = (
        record.get if isinstance(record, dict) else lambda k: getattr(record, k, None)
    )
    if not getter("tool_name"):
        return ""
    return str(getter("tool_input_excerpt") or "")


def find_bypass(
    records: Iterable[Any], rows: Iterable[ToolRow], session: str
) -> list[Bypass]:
    """One signal per tool whose script path appears in a tool call input."""
    texts = [text for text in map(_input_text, records) if text]
    return [
        Bypass(row.skill, row.step, session)
        for row in rows
        if any(script_suffix(row.skill, row.step) in text for text in texts)
    ]


def load_rows() -> tuple[list[ToolRow], str]:
    """Registry rows of the installed modules, or no rows and a notice.

    The check is advisory: a malformed registry or a provider that fails to
    import must not abort session inspection.
    """
    try:
        return all_rows(module_roots()), ""
    except Exception as error:  # noqa: BLE001 - advisory check never aborts a run
        return [], f"tool bypass check skipped: {error}"[:200]


def bypass_metric(
    records: Iterable[Any], session: str, rows: Iterable[ToolRow]
) -> list[dict[str, str]]:
    """Bypass signals against the registry rows, as session metric data."""
    return [signal.as_dict() for signal in find_bypass(list(records), rows, session)]
