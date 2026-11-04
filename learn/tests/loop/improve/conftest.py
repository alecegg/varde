from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from varde_learn.docs.pages import comments
from varde_learn.loop.improve import approval


@pytest.fixture(autouse=True)
def private_data_home(tmp_path, monkeypatch) -> Path:
    """Keep the step-tool launcher out of the real data directory."""
    home = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    return home


@pytest.fixture
def approve() -> Callable[..., Path]:
    """Record a decision answer in the comments log of a report page."""

    def answer(memory: Path, record_id: str, verdict: str = "approved") -> Path:
        page = approval.report_dir(memory) / "2026-11-01.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        if not page.exists():
            page.write_text(f"## {record_id}\n\n```ui id={record_id}\n```\n")
        extra = {"kind": "decision", "item": record_id, "verdict": verdict}
        comments.append_comment(page, "b1", "", verdict, "user", extra)
        return page

    return answer
