from __future__ import annotations

import os
import plistlib
import shlex
import subprocess
from pathlib import Path

from varde_code.index import supervise


def _stub_command(directory: Path, name: str, log: Path, *, output: str = "") -> None:
    script = directory / name
    script.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" >> {shlex.quote(str(log))}\n"
        f"printf '%s' {shlex.quote(output)}\n"
    )
    script.chmod(0o755)


def test_ensure_installs_python_specific_launch_agent_and_waits(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    binary = tmp_path / "bin" / "varde-python"
    binary.parent.mkdir()
    binary.touch()
    commands = tmp_path / "commands"
    commands.mkdir()
    log = tmp_path / "launchctl.log"
    _stub_command(commands, "launchctl", log)
    _stub_command(commands, "id", log, output="501\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{commands}:{os.environ['PATH']}")

    path = supervise.ensure(repo, binary=binary, system="Darwin")

    definition = plistlib.loads(path.read_bytes())
    assert path.parent == home / "Library/LaunchAgents"
    assert definition["Label"].startswith("varde-code-py-")
    assert definition["ProgramArguments"] == [
        str(binary.resolve()),
        "setup",
        "watch",
        "--repo",
        str(repo),
    ]
    assert "bootstrap\ngui/501" in log.read_text()
    assert f"print\ngui/501/{definition['Label']}" in log.read_text()


def test_ensure_installs_systemd_unit_and_waits(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    binary = tmp_path / "varde-python"
    binary.touch()
    commands = tmp_path / "commands"
    commands.mkdir()
    log = tmp_path / "systemctl.log"
    _stub_command(commands, "systemctl", log, output="active\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{commands}:{os.environ['PATH']}")

    path = supervise.ensure(repo, binary=binary, system="Linux")

    definition = path.read_text()
    assert path.parent == home / ".config/systemd/user"
    assert path.name.startswith("varde-code-py-")
    assert f'ExecStart="{binary.resolve()}" setup watch --repo "{repo}"' in definition
    assert log.read_text().splitlines() == [
        "--user",
        "daemon-reload",
        "--user",
        "enable",
        "--now",
        f"{path.stem}.service",
        "--user",
        "is-active",
        f"{path.stem}.service",
    ]


def test_ensure_times_out_when_supervisor_never_reports_ready(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    binary = tmp_path / "varde-python"
    binary.touch()

    def inactive(args):
        if "is-active" in args:
            return subprocess.CompletedProcess(args, 3, "inactive", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(supervise, "_run", inactive)

    try:
        supervise.ensure(repo, binary=binary, system="Linux", timeout=0)
    except TimeoutError as error:
        assert "did not become ready" in str(error)
    else:
        raise AssertionError("ensure should fail if the supervisor never becomes ready")


def test_stop_and_list_use_only_python_registration(tmp_path, monkeypatch):
    home = tmp_path / "home"
    config = tmp_path / "config"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.setattr(supervise.platform, "system", lambda: "Linux")
    commands = tmp_path / "commands"
    commands.mkdir()
    log = tmp_path / "systemctl.log"
    _stub_command(commands, "systemctl", log, output="inactive\n")
    monkeypatch.setenv("PATH", f"{commands}:{os.environ['PATH']}")

    path = supervise.service_path(repo)
    path.parent.mkdir(parents=True)
    path.write_text("python watcher")
    registry = config / "code" / "watch-services-py"
    registry.mkdir(parents=True)
    (registry / f"{supervise.service_name(repo)}.json").write_text(f'"{repo}"')

    entries = supervise.list_instances()
    outcome = supervise.stop([repo])

    assert len(entries) == 1
    assert entries[0]["registered"] is True
    assert outcome == {"pid": 0, "repos": [str(repo.resolve())], "stopped": False}
    assert not path.exists()
    assert not list(registry.glob("*.json"))
    assert "varde-code-py-" in log.read_text()
