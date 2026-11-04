"""Opt-in real transcript spend check for local harness data."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from varde_learn.loop.diagnose.list import discover_root
from varde_learn.loop.review import run, spend


@pytest.mark.skipif(
    not os.environ.get("VARDE_LEARN_TRANSCRIPTS_ROOT"),
    reason="set VARDE_LEARN_TRANSCRIPTS_ROOT to a Claude projects root",
)
def test_real_claude_transcripts_have_windowed_spend() -> None:
    root = Path(os.environ["VARDE_LEARN_TRANSCRIPTS_ROOT"])
    start = datetime(2026, 10, 16, 12, tzinfo=UTC)
    end = datetime.now(UTC)
    discovered = discover_root("claude", root, window_start=start)
    sessions = []
    for item in discovered.sessions:
        row = {
            "harness": "claude",
            "session_id": item.session_id,
            "root": str(root),
            "path": item.path,
            "kind": item.kind,
            "parent_id": item.parent_id,
        }
        records, _metrics = run._inspect(row)
        sessions.append(
            spend.prepare_session(
                {
                    "harness": "claude",
                    "session_id": item.session_id,
                    "records": records,
                    "first_prompt": next(
                        (
                            record.text_excerpt
                            for record in records
                            if getattr(record, "text_excerpt", None)
                        ),
                        "",
                    ),
                    "is_subagent": item.kind == "subagent",
                    "parent_session_id": item.parent_id,
                },
                start,
                end,
            )
        )

    totals = spend.build(sessions, ["claude"], start, end)["snapshot"]["totals"]
    assert totals["calls"] > 0
    assert totals["weighted"] > 0
