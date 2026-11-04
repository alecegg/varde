"""Service install and start default the runner switch on when it is unset."""

import platform
import subprocess
import tomllib
from pathlib import Path

import pytest
from test_service_text import FakeLaunchctl
from varde_runner import service


@pytest.fixture
def config_path(tmp_path, monkeypatch) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    executable = tmp_path / ".local/bin/varde-runner"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(service, "installed_runner_path", lambda: str(executable))
    monkeypatch.setattr(service.subprocess, "run", _ok)
    return config_dir / "config.toml"


def _ok(command, **_):
    return subprocess.CompletedProcess(command, 0)


def _fail(command, **_):
    raise subprocess.CalledProcessError(1, command)


def _enabled(path: Path) -> bool | None:
    if not path.exists():
        return None
    return tomllib.loads(path.read_text()).get("runner", {}).get("enabled")


def test_install_with_key_absent_writes_true(config_path, tmp_path):
    service._manage("install", working_dir=tmp_path)
    assert _enabled(config_path) is True


def test_start_with_key_absent_writes_true(config_path):
    service._manage("start")
    assert _enabled(config_path) is True


def test_explicit_false_is_kept(config_path, tmp_path):
    config_path.write_text("[runner]\nenabled = false\n")
    service._manage("install", working_dir=tmp_path)
    service._manage("start")
    assert _enabled(config_path) is False


def test_failed_start_writes_nothing(config_path, monkeypatch):
    monkeypatch.setattr(service.subprocess, "run", _fail)
    with pytest.raises(subprocess.CalledProcessError):
        service._manage("start")
    assert _enabled(config_path) is None


def test_stop_writes_nothing(config_path):
    service._manage("stop")
    assert _enabled(config_path) is None


def test_invalid_config_does_not_fail_start(config_path, capsys):
    config_path.write_text("[runner\n")
    service._manage("start")
    captured = capsys.readouterr()
    assert "Runner switch not set" in captured.err
    assert "varde runner on" in captured.err
    assert "Runner switch not set" not in captured.out
    assert config_path.read_text() == "[runner\n"


@pytest.fixture
def launchd(config_path, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service.time, "sleep", lambda _: None)


def test_launchd_install_and_start_write_true(
    launchd, config_path, monkeypatch, tmp_path
):
    monkeypatch.setattr(service.subprocess, "run", FakeLaunchctl().run)
    service._manage("install", working_dir=tmp_path)
    assert _enabled(config_path) is True
    config_path.unlink()
    service._manage("start")
    assert _enabled(config_path) is True


def test_launchd_failed_bootstrap_writes_nothing(
    launchd, config_path, monkeypatch, tmp_path
):
    fake = FakeLaunchctl(fail={"bootstrap": (5, "denied")})
    monkeypatch.setattr(service.subprocess, "run", fake.run)
    with pytest.raises(SystemExit, match="bootstrap failed"):
        service._manage("install", working_dir=tmp_path)
    assert _enabled(config_path) is None
