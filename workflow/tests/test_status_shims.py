from __future__ import annotations

import subprocess
import sys

from varde_workflow.commands import status, watch


def test_status_time_shim_is_patchable_and_used(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_time() -> float:
        calls.append(True)
        return 123.0

    monkeypatch.setattr(status.time, "time", fake_time)

    assert status.time.time is fake_time
    status.collect_from(tmp_path)
    assert calls


def test_watch_shims_are_the_names_used_by_watch(monkeypatch, tmp_path) -> None:
    branches_calls = []
    monkeypatch.setattr(
        watch, "_read_branches", lambda repo: branches_calls.append(repo) or {}
    )
    monkeypatch.setattr(watch, "_read_worktrees", lambda repo: {})
    monkeypatch.setattr(watch, "read_bindings", lambda working: [])

    assert watch.scan(tmp_path, tmp_path, now=123.0) == []
    assert branches_calls == [tmp_path]

    monkeypatch.setattr(watch, "awaiting_user", lambda *_args: "patched approval")
    monkeypatch.setattr(
        watch, "approved_merge_detail", lambda *_args: "patched merge detail"
    )
    assert watch.watch_state_detail(
        "stale",
        "stale detail",
        {"id": "plan"},
        tmp_path,
        [],
        [],
        tmp_path,
        123.0,
        0.0,
        123,
    ) == ("blocked", "patched merge detail", False)


def test_status_shim_contract_names() -> None:
    assert callable(status.collect_plan_paths)
    assert callable(status.status_bucket)
    assert callable(status.parse_status_at)
    assert callable(watch._read_branches)
    assert callable(watch.awaiting_user)
    assert callable(watch.approved_merge_detail)


def test_importing_plans_does_not_import_testing() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, varde_data.plans; "
                "assert 'varde_data.testing' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_approved_merge_grace_matches_data_view() -> None:
    from varde_data.views.watch import APPROVED_MERGE_GRACE_SECONDS as view_grace
    from varde_workflow.merge_state import APPROVED_MERGE_GRACE_SECONDS

    assert view_grace == APPROVED_MERGE_GRACE_SECONDS
