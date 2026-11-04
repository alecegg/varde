from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_user_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("VARDE_LEARN_STORE", raising=False)
