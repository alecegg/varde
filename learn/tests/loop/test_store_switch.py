"""``varde learn store`` status, migrate, verify and retire dispatch."""

import json
import sys
import types
from pathlib import Path

import pytest
from varde_data.learn_store_mode import read_learn_mode
from varde_learn.module import register


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store = tmp_path / "learn"
    store.mkdir()
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    return store


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = register().run(["learn", "store", *args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _install_handlers(
    monkeypatch: pytest.MonkeyPatch, domain: str, *, verify_ok: bool = True
) -> list[str]:
    calls: list[str] = []
    module = types.ModuleType(f"varde_data.learn_handlers.{domain}")
    module.rows = lambda root: 3  # type: ignore[attr-defined]
    module.migrate = lambda root, *, dry_run: (  # type: ignore[attr-defined]
        calls.append(f"migrate dry={dry_run}") or {"ok": True}
    )
    module.verify = lambda root: (  # type: ignore[attr-defined]
        calls.append("verify") or {"ok": verify_ok}
    )
    module.retire = lambda root: calls.append("retire") or {}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return calls


def test_status_reports_all_domains_on_files(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (root / "friction.jsonl").write_text("")
    code, out, _ = _run(capsys, "status", "--json")
    payload = json.loads(out)
    assert code == 0
    assert payload["ok"] is True
    data = payload["data"]
    assert data["database"] is None
    assert data["generation"] == 0
    assert data["domains"] == {
        "friction": {"mode": "files", "rows": 0, "files_present": True},
        "ledger": {"mode": "files", "rows": 0, "files_present": False},
        "calls": {"mode": "files", "rows": 0, "files_present": False},
    }


def test_migrate_flips_only_that_domain_and_keeps_sources(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_handlers(monkeypatch, "calls")
    source = root / "cli_calls.jsonl"
    source.write_text("{}\n")

    code, out, _ = _run(capsys, "migrate", "--domain", "calls", "--json")

    assert code == 0, out
    record = read_learn_mode(root)
    assert (record.friction, record.ledger, record.calls) == (
        "files",
        "files",
        "sqlite",
    )
    assert record.generation == 1
    assert source.exists()
    assert calls == ["migrate dry=False"]


def test_dry_run_does_not_flip(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_handlers(monkeypatch, "calls")
    code, _, _ = _run(capsys, "migrate", "--domain", "calls", "--dry-run")
    assert code == 0
    assert read_learn_mode(root).generation == 0
    assert calls == ["migrate dry=True"]


def test_second_migrate_is_refused(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_handlers(monkeypatch, "calls")
    assert _run(capsys, "migrate", "--domain", "calls")[0] == 0
    code, _, err = _run(capsys, "migrate", "--domain", "calls")
    assert code == 2
    assert "already on sqlite" in err


def test_retire_needs_sqlite_and_a_passing_verify(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_handlers(monkeypatch, "calls", verify_ok=False)
    assert _run(capsys, "retire", "--domain", "calls")[0] == 2
    assert _run(capsys, "migrate", "--domain", "calls")[0] == 0
    code, out, _ = _run(capsys, "retire", "--domain", "calls", "--json")
    assert code == 1
    assert json.loads(out)["data"]["retired"] is False
    assert "retire" not in calls


def test_retire_runs_handler_after_verify(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_handlers(monkeypatch, "calls")
    _run(capsys, "migrate", "--domain", "calls")
    assert _run(capsys, "retire", "--domain", "calls")[0] == 0
    assert calls[-2:] == ["verify", "retire"]


def test_missing_handlers_and_arguments_are_usage_errors(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "varde_data.learn_handlers.calls", None)
    code, _, err = _run(capsys, "migrate", "--domain", "calls")
    assert code == 2
    assert "not installed" in err
    assert _run(capsys, "verify")[0] == 2
    assert _run(capsys, "status", "--dry-run")[0] == 2
    assert read_learn_mode(root).generation == 0


def test_call_append_racing_a_flip_is_refused_not_lost(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    import time

    from varde_data.learn_store_mode import exclusive_store_lock, flip_domain_locked
    from varde_learn.loop.calls import append_call

    row = {"ts": "2026-01-01T00:00:00Z", "command": "x", "status": "success"}
    assert append_call(row)  # type: ignore[arg-type]
    results: list[bool] = []
    with exclusive_store_lock(root):
        thread = threading.Thread(
            target=lambda: results.append(append_call(row))  # type: ignore[arg-type]
        )
        thread.start()
        time.sleep(0.05)
        flip_domain_locked(root, "calls", "sqlite")
    thread.join(10)
    assert results == [False]
    assert len((root / "cli_calls.jsonl").read_text().splitlines()) == 1


def test_concurrent_migrate_rechecks_mode_under_lock(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_handlers(monkeypatch, "calls")
    from varde_data.learn_store_mode import flip_domain_locked

    flip_domain_locked(root, "calls", "sqlite")
    code, _, err = _run(capsys, "migrate", "--domain", "calls")
    assert code == 2
    assert "already on sqlite" in err
    assert calls == []
