"""Keep workflow tests away from the user's Varde configuration and memory."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_varde_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / ".home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(home / ".config" / "varde"))
    monkeypatch.delenv("VARDE_WORKING_DIR", raising=False)
    monkeypatch.delenv("VARDE_ADDRESS", raising=False)
