from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest
from varde.setup.runner_switch import run


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    home.mkdir()
    bin_dir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(home / "cfg"))
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.delenv("VARDE_RUNNER_ENABLED", raising=False)
    return tmp_path


def config(env: Path) -> str:
    path = env / "home" / "cfg" / "config.toml"
    return path.read_text() if path.exists() else ""


def fake_runner(env: Path, fail: str = "") -> Path:
    """Install a varde-runner that logs `service <action>` and fails on `fail`."""
    log = env / "calls.log"
    script = env / "bin" / "varde-runner"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> {log}\n'
        f'[ "$2" = "{fail}" ] && {{ echo boom >&2; exit 2; }}\n'
        'echo "state for $2"\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return log


def install_unit(env: Path) -> None:
    if sys.platform == "darwin":
        unit = env / "home/Library/LaunchAgents/org.varde.runner.plist"
    else:
        unit = env / "home/.config/systemd/user/varde-runner.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("")


def calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def test_off_writes_switch_then_stops_service(env: Path) -> None:
    log = fake_runner(env)
    install_unit(env)
    assert run(["off"], None) == 0
    assert "enabled = false" in config(env)
    assert calls(log) == ["service stop"]


def test_off_without_executable_is_a_note(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["off"], None) == 0
    assert "enabled = false" in config(env)
    assert "note:" in capsys.readouterr().out


def test_off_with_absent_service_does_not_stop(env: Path) -> None:
    log = fake_runner(env)
    assert run(["off"], None) == 0
    assert calls(log) == []


def test_off_failing_stop_warns_and_keeps_switch_off(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_runner(env, fail="stop")
    install_unit(env)
    assert run(["off"], None) == 1
    assert "enabled = false" in config(env)
    assert "warning" in capsys.readouterr().err


def test_on_starts_service_then_writes_switch(env: Path) -> None:
    log = fake_runner(env)
    assert run(["on"], None) == 0
    assert calls(log) == ["service start"]
    assert "enabled = true" in config(env)


def test_on_failing_start_leaves_switch_unchanged(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_runner(env, fail="start")
    assert run(["on"], None) == 1
    assert config(env) == ""
    assert "switch unchanged" in capsys.readouterr().err


def test_on_without_executable_fails_and_leaves_switch(env: Path) -> None:
    assert run(["on"], None) == 1
    assert config(env) == ""


def test_on_invalid_config_exits_one(env: Path) -> None:
    fake_runner(env)
    cfg = env / "home" / "cfg"
    cfg.mkdir()
    (cfg / "config.toml").write_text("[runner\n")
    assert run(["on"], None) == 1


def test_status_reports_default_source_and_service(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_runner(env)
    assert run(["status"], None) == 0
    out = capsys.readouterr().out
    assert "off (source: default)" in out
    assert "state for status" in out


def test_status_warns_when_env_disagrees_with_file(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_runner(env)
    run(["on"], None)
    capsys.readouterr()
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "0")
    assert run(["status"], None) == 0
    captured = capsys.readouterr()
    assert "off (source: env)" in captured.out
    assert "overrides config.toml" in captured.err


def test_status_without_executable(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["status"], None) == 0
    assert "not found" in capsys.readouterr().out


def test_missing_action_is_usage_error(env: Path) -> None:
    assert run([], None) != 0


def test_off_and_on_warn_when_env_overrides_the_write(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_runner(env)
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "1")
    assert run(["off"], None) == 0
    err = capsys.readouterr().err
    assert "overrides config.toml" in err
    assert "stays on" in err
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "0")
    assert run(["on"], None) == 0
    assert "stays off" in capsys.readouterr().err


def test_off_without_override_has_no_warning(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["off"], None) == 0
    assert "overrides" not in capsys.readouterr().err


def test_off_invalid_config_exits_one(env: Path) -> None:
    cfg = env / "home" / "cfg"
    cfg.mkdir()
    (cfg / "config.toml").write_text("[runner\n")
    assert run(["off"], None) == 1


def test_executable_falls_back_to_local_bin(env: Path) -> None:
    log = fake_runner(env)
    local = env / "home" / ".local" / "bin"
    local.mkdir(parents=True)
    (env / "bin" / "varde-runner").rename(local / "varde-runner")
    assert run(["on"], None) == 0
    assert calls(log) == ["service start"]


def test_status_warns_when_env_on_over_file_off(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run(["off"], None)
    capsys.readouterr()
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "1")
    assert run(["status"], None) == 0
    captured = capsys.readouterr()
    assert "on (source: env)" in captured.out
    assert "[runner] enabled = false" in captured.err
