from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from varde_workflow.commands import status

sys.path.insert(0, str(Path(__file__).parent))
from golden.plans.builder import FIXED_CLOCK, build, check_snapshot


def test_plan_status_golden_is_stable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TZ", "UTC")
    working, repo = build(tmp_path)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(working)
    monkeypatch.setattr(status.time, "time", lambda: FIXED_CLOCK)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert status.run(SimpleNamespace(json=True, repo=repo)) == 0
    stdout = output.getvalue()
    check_snapshot("plans-read", stdout, tmp_path)
    report = json.loads(stdout)["data"]
    rendered = json.dumps(report, sort_keys=True)
    assert '"title": "Nested"' in rendered
    assert '"title": "Duplicate A"' in rendered and '"title": "Duplicate B"' in rendered
    assigned = next(plan for plan in report["plans"] if plan["id"] == "assigned")
    assert assigned["assigned_to"] == "agent-1"
    assert assigned["awaiting_user"] == "Please approve the assigned plan."
    assert assigned["now"] == "Active task in progress"
    assert '"title": "Archived"' not in rendered
    assert report["skipped"] == 2
