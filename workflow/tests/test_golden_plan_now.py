from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace

from varde_workflow.commands import now

sys.path.insert(0, str(Path(__file__).parent))
from golden.plans.builder import build, check_snapshot


def test_now_line_golden(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TZ", "UTC")
    working, _ = build(tmp_path)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(working)
    args = SimpleNamespace(
        plan="date-suffix",
        text="waiting for review",
        waiting=None,
        clear=False,
        json=True,
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert now.run(args) == 0
    check_snapshot("plans-now", output.getvalue(), tmp_path)
    date_plan = working / "plans/2026-10-23-date-suffix/plan.md"
    assert now.resolve_plan("date-suffix", working, working / "plans") == date_plan
    assert now.read_line(working / "plans", date_plan) == "waiting for review"
