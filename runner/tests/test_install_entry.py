from __future__ import annotations

import sys
from pathlib import Path

from varde_runner import installed_runner_path, main


def test_installed_runner_path_prefers_stable_user_path(
    tmp_path: Path, monkeypatch
) -> None:
    stable_path = tmp_path / ".local" / "bin" / "varde-runner"
    stable_path.parent.mkdir(parents=True)
    stable_path.touch()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert installed_runner_path() == str(stable_path)


def test_installed_runner_path_falls_back_to_current_executable(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["/current/varde-runner"])

    assert installed_runner_path() == "/current/varde-runner"


def test_runner_entry_point_reports_version(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["varde-runner", "--version"])

    main()

    assert capsys.readouterr().out == "0.1.0\n"
