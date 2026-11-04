from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_workflow.plan_gate import _scan


@pytest.mark.parametrize("code", ["index_missing", "index_stale"])
def test_scan_without_usable_index_names_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=f'{{"code":"{code}"}}', stderr="", returncode=1
        ),
    )

    status, detail = _scan(tmp_path, [])

    assert status == "fail"
    assert "`varde map build` on the main checkout" in detail
    assert "varde map packs status" in detail


def test_scan_fails_closed_for_other_json_tool_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout='{"ok":false,"data":{"error":{"code":"tool_error"}}}',
            stderr="",
            returncode=1,
        ),
    )

    status, detail = _scan(tmp_path, [])

    assert status == "fail"
    assert "tool_error" in detail


def test_index_code_in_finding_message_does_not_trigger_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=(
                '{"ok":true,"data":{"findings":[{"severity":"warning",'
                '"message":"index_missing"}]}}'
            ),
            stderr="",
            returncode=0,
        ),
    )

    status, detail = _scan(tmp_path, [])

    assert status == "pass"
    assert "recover" not in detail


def test_linked_worktree_missing_index_warns_and_main_checkout_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout='{"code":"index_missing"}', stderr="", returncode=1
        ),
    )
    main = tmp_path / "main"
    (main / ".git").mkdir(parents=True)
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / ".git").write_text("gitdir: elsewhere\n")

    warned, detail = _scan(linked, [])
    failed, _ = _scan(main, [])

    assert warned == "warning"
    assert "changed files not scanned" in detail
    assert failed == "fail"
