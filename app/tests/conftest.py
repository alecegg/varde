from __future__ import annotations

import pytest
from varde.setup.hooks_install import doctor as hooks_doctor


@pytest.fixture(autouse=True)
def isolated_learn_store(monkeypatch, tmp_path):
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "learn"))


@pytest.fixture(autouse=True)
def stub_codex_hooks_query(monkeypatch):
    monkeypatch.setattr(hooks_doctor, "query_hooks", lambda _: {})


@pytest.fixture(autouse=True)
def runner_switch_on(monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "1")
