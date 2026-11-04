from __future__ import annotations

from pathlib import Path

import pytest
from varde_runner import merge_allowed_hosts
from varde_runner.relay_cli import parse_relay_mode


def test_merge_allowed_hosts_combines_sources() -> None:
    merged = merge_allowed_hosts("Cfg.ts.net", "cli.ts.net", "a, B ,,cfg.ts.net")
    assert merged == {"cfg.ts.net", "cli.ts.net", "a", "b"}


@pytest.mark.parametrize("value", [None, "", "0", "off"])
def test_relay_mode_off_values(value: str | None) -> None:
    assert parse_relay_mode(value) is None


@pytest.mark.parametrize(
    ("value", "mode"), [("1", "data"), ("data", "data"), ("cli", "cli")]
)
def test_relay_mode_on_values(value: str, mode: str) -> None:
    assert parse_relay_mode(value) == mode


def test_relay_mode_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="VARDE_RUNNER_RELAY"):
        parse_relay_mode("bogus")


def _serve(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict:
    import os
    import sys

    import varde_runner
    import varde_runner.web

    seen: dict = {}
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["varde-runner", "serve"])
    monkeypatch.setattr(
        varde_runner.web, "create_app", lambda **kw: seen.update(kw) or "app"
    )
    monkeypatch.setattr(varde_runner.uvicorn, "run", lambda *a, **kw: None)
    varde_runner.main()
    seen["relay"] = os.environ.get("VARDE_RUNNER_RELAY")
    return seen


def test_serve_defaults_relay_on_and_reads_config_hosts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("VARDE_RUNNER_RELAY", raising=False)
    monkeypatch.setenv("VARDE_RUNNER_ALLOWED_HOSTS", "env.ts.net")
    (tmp_path / "runner.toml").write_text('allowed_hosts = ["cfg.ts.net"]')
    seen = _serve(monkeypatch, tmp_path)
    assert seen["relay"] == "data"
    assert seen["allowed_hosts"] == {"cfg.ts.net", "env.ts.net"}


def test_serve_keeps_explicit_relay_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VARDE_RUNNER_RELAY", "off")
    assert _serve(monkeypatch, tmp_path)["relay"] == "off"
