import plistlib
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
from varde_runner.service import _doctor, _manage, render_launchd, render_systemd


def test_launchd_render_contains_supervision_and_logs(tmp_path: Path):
    value = plistlib.loads(
        render_launchd("/home/test/.local/bin/varde-runner", tmp_path).encode()
    )
    assert value["ProgramArguments"] == ["/home/test/.local/bin/varde-runner", "serve"]
    assert value["RunAtLoad"] is True and value["KeepAlive"] is True
    assert str(tmp_path / "Library/Logs/Varde") in value["StandardOutPath"]
    assert str(tmp_path / ".local/bin") in value["EnvironmentVariables"]["PATH"]
    assert value["EnvironmentVariables"]["VARDE_RUNNER_SERVICE"] == "launchd"


def test_systemd_render_uses_stable_path_and_environment_file(tmp_path: Path):
    text = render_systemd(home=tmp_path)
    assert "Type=simple" in text and "Restart=always" in text
    assert "WantedBy=default.target" in text
    assert f"EnvironmentFile=-{tmp_path}/.config/varde/runner.env" in text
    assert f'ExecStart="{tmp_path}/.local/bin/varde-runner" serve' in text
    assert f"{tmp_path}/.local/bin" in text
    assert 'Environment="VARDE_RUNNER_SERVICE=systemd"' in text


def test_only_user_systemd_unit_is_rendered():
    assert "WantedBy=default.target" in render_systemd()


def test_service_path_includes_discovered_cli_directories(tmp_path, monkeypatch):
    from varde_runner import service

    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(
        service.shutil,
        "which",
        lambda name: f"/opt/{name}/bin/{name}",
    )
    plist = plistlib.loads(render_launchd(home=tmp_path).encode())
    path = plist["EnvironmentVariables"]["PATH"]
    assert "/opt/claude/bin" in path and "/opt/codex/bin" in path
    assert "/usr/bin" in path
    unit = render_systemd(home=tmp_path)
    assert "/opt/claude/bin" in unit and "/opt/codex/bin" in unit


def test_systemd_quotes_paths_with_spaces(tmp_path):
    home = tmp_path / "home with spaces"
    text = render_systemd(home=home)
    assert f'ExecStart="{home}/.local/bin/varde-runner" serve' in text
    assert f"EnvironmentFile=-{home}/.config/varde/runner.env" in text


def test_doctor_fallback_probes_shell_workspace(tmp_path, monkeypatch, capsys):
    from varde_runner import service

    monkeypatch.chdir(tmp_path)
    requests = []

    def refused(*args, **kwargs):
        requests.append(args[0].full_url)
        raise URLError(ConnectionRefusedError())

    monkeypatch.setattr(service.urllib.request, "urlopen", refused)
    calls = []
    from varde_runner.service import probe

    def probe_paths(paths, timeout):
        calls.append((paths, timeout))
        return {paths[0]: "ok"}

    monkeypatch.setattr(probe, "probe_paths", probe_paths)
    _doctor(9123)
    assert requests == ["http://127.0.0.1:9123/api/probe"]
    assert calls == [([str(tmp_path)], 2.0)]
    assert "may differ from the service" in capsys.readouterr().out


def test_doctor_timeout_names_path_and_real_runner(monkeypatch, capsys):
    from varde_runner import service

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"results":{"/workspace with spaces":"timeout"}}'

    monkeypatch.setattr(service.urllib.request, "urlopen", lambda *a, **k: Response())
    monkeypatch.setattr(
        service, "installed_runner_path", lambda: "/real/bin/varde-runner"
    )
    monkeypatch.setattr(service.sys, "executable", "/python/bin/python")
    _doctor(19123)
    output = capsys.readouterr().out
    assert "Workspace path timeout: /workspace with spaces" in output
    assert "/real/bin/varde-runner" in output
    assert "/python/bin/python" in output
    assert "0.0s" not in output


def test_doctor_http_error_is_not_reported_as_unavailable(monkeypatch, capsys):
    from varde_runner import service

    def fail(*args, **kwargs):
        raise HTTPError("url", 404, "missing route", Message(), None)

    monkeypatch.setattr(service.urllib.request, "urlopen", fail)
    _doctor(8766)
    output = capsys.readouterr().out
    assert "HTTP 404" in output
    assert "Runner unavailable" not in output


def test_doctor_falls_back_to_the_shell_probe_when_the_runner_needs_pairing(
    tmp_path, monkeypatch, capsys
):
    from varde_runner import service
    from varde_runner.service import probe

    def forbidden(*args, **kwargs):
        raise HTTPError("url", 403, "Forbidden", Message(), None)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(service.urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(probe, "probe_paths", lambda paths, timeout: {paths[0]: "ok"})
    _doctor(8767)
    output = capsys.readouterr().out
    assert "needs a paired browser" in output
    assert "Shell probe complete" in output
    assert "HTTP 403" not in output


def test_install_rejects_missing_runner_path(tmp_path, monkeypatch):
    import pytest
    from varde_runner import service

    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        service, "installed_runner_path", lambda: str(tmp_path / "missing")
    )
    with pytest.raises(SystemExit, match="Runner executable not found"):
        _manage("install", working_dir=tmp_path / "data")


def test_version_comes_from_installed_distribution():
    import runpy
    import tomllib

    from varde_runner import VERSION

    metadata = tomllib.loads(Path("runner/pyproject.toml").read_text())
    assert metadata["project"]["version"] == VERSION
    assert runpy.run_path("runner/pex/build.py")["runner_version"]() == VERSION


def test_second_launchd_install_boots_out_before_bootstrap(tmp_path, monkeypatch):
    import platform

    from varde_runner import service

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    launchctl = FakeLaunchctl(loaded=True)
    monkeypatch.setattr(service.subprocess, "run", launchctl.run)
    monkeypatch.setattr(service.time, "sleep", lambda _: None)
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    executable = tmp_path / ".local/bin/varde-runner"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(service, "installed_runner_path", lambda: str(executable))
    service._manage("install", working_dir=tmp_path / "data")
    verbs = [c[0] for c in launchctl.calls if c[0] != "print"]
    assert verbs == ["bootout", "bootstrap"]
    assert launchctl.loaded


def test_install_keeps_existing_runner_environment(tmp_path, monkeypatch):
    import platform

    from varde_runner import service

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    executable = tmp_path / ".local/bin/varde-runner"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(service, "installed_runner_path", lambda: str(executable))
    env_file = tmp_path / ".config/varde/runner.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("CUSTOM=kept\n")
    monkeypatch.setattr(service, "_run", lambda *args, **kwargs: None)
    success = type("R", (), {"returncode": 0})()
    monkeypatch.setattr(service.subprocess, "run", lambda *args, **kwargs: success)
    _manage("install", working_dir=tmp_path / "data")
    assert env_file.read_text() == "CUSTOM=kept\n"


class FakeLaunchctl:
    """Stands in for launchctl: bootout takes `lag` print calls to finish."""

    def __init__(self, loaded=False, lag=0, fail=None):
        self.loaded = loaded
        self.lag = lag
        self.pending = 0
        self.fail = dict(fail or {})
        self.calls = []

    def run(self, command, **kwargs):
        assert command[0] == "launchctl"
        verb = command[1]
        self.calls.append(command[1:])
        code, err = self.fail.get(verb, (0, ""))
        if isinstance(code, list):
            code = code.pop(0) if code else 0
        if code:
            return self._result(code, err)
        if verb == "bootout" and self.loaded:
            self.loaded, self.pending = False, self.lag
        elif verb == "bootstrap":
            self.loaded = True
        elif verb == "print":
            if self.pending:
                self.pending -= 1
                return self._result(0, "")
            return self._result(0 if self.loaded else 113, "")
        return self._result(0, "")

    @staticmethod
    def _result(code, err):
        return type("R", (), {"returncode": code, "stdout": "", "stderr": err})()


def _launchd(tmp_path, monkeypatch, action, launchctl, plist=True):
    import platform

    from varde_runner import service

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(service.subprocess, "run", launchctl.run)
    monkeypatch.setattr(service.time, "sleep", lambda _: None)
    if plist:
        target = tmp_path / "Library/LaunchAgents" / f"{service.LABEL}.plist"
        target.parent.mkdir(parents=True)
        target.touch()
    service._manage(action)
    return [c[0] for c in launchctl.calls]


def test_launchd_stop_waits_until_job_is_gone(tmp_path, monkeypatch):
    launchctl = FakeLaunchctl(loaded=True, lag=3)
    verbs = _launchd(tmp_path, monkeypatch, "stop", launchctl)
    assert verbs[0] == "bootout" and verbs.count("print") == 4
    assert not launchctl.loaded and launchctl.pending == 0


def test_launchd_stop_fails_when_job_never_unloads(tmp_path, monkeypatch):
    from varde_runner import service

    launchctl = FakeLaunchctl(loaded=True, lag=10**6)
    ticks = iter(range(1000))
    monkeypatch.setattr(service.time, "monotonic", lambda: next(ticks))
    with pytest.raises(SystemExit, match="still loaded"):
        _launchd(tmp_path, monkeypatch, "stop", launchctl)


def test_launchd_stop_when_not_loaded_is_clean(tmp_path, monkeypatch):
    launchctl = FakeLaunchctl(loaded=False, fail={"bootout": (3, "No such process")})
    assert _launchd(tmp_path, monkeypatch, "stop", launchctl) == ["bootout", "print"]


def test_launchd_start_bootstraps_then_kickstarts(tmp_path, monkeypatch):
    launchctl = FakeLaunchctl(loaded=False)
    verbs = _launchd(tmp_path, monkeypatch, "start", launchctl)
    assert [v for v in verbs if v != "print"] == ["bootstrap", "kickstart"]


def test_launchd_start_kickstarts_loaded_job_without_bootstrap(tmp_path, monkeypatch):
    launchctl = FakeLaunchctl(loaded=True)
    verbs = _launchd(tmp_path, monkeypatch, "start", launchctl)
    assert [v for v in verbs if v != "print"] == ["kickstart"]


def test_launchd_start_retries_bootstrap_once(tmp_path, monkeypatch):
    launchctl = FakeLaunchctl(
        loaded=False, fail={"bootstrap": ([5, 0], "Bootstrap failed: 5")}
    )
    verbs = _launchd(tmp_path, monkeypatch, "start", launchctl)
    assert verbs.count("bootstrap") == 2 and verbs[-1] == "kickstart"


def test_launchd_print_error_is_not_treated_as_unloaded(tmp_path, monkeypatch):
    launchctl = FakeLaunchctl(
        loaded=True, fail={"print": (1, "Operation not permitted")}
    )
    with pytest.raises(SystemExit, match="print failed.*not permitted"):
        _launchd(tmp_path, monkeypatch, "stop", launchctl)


def test_launchd_start_fails_loudly_with_launchctl_error(tmp_path, monkeypatch):
    launchctl = FakeLaunchctl(
        loaded=False, fail={"bootstrap": (5, "Bootstrap failed: 5: Input/output error")}
    )
    with pytest.raises(SystemExit, match="bootstrap failed.*Input/output error"):
        _launchd(tmp_path, monkeypatch, "start", launchctl)
    assert [c[0] for c in launchctl.calls].count("bootstrap") == 2


def test_launchd_start_reports_kickstart_failure(tmp_path, monkeypatch):
    launchctl = FakeLaunchctl(loaded=True, fail={"kickstart": (113, "not found")})
    with pytest.raises(SystemExit, match="kickstart failed.*not found"):
        _launchd(tmp_path, monkeypatch, "start", launchctl)


def test_launchd_stop_then_start_races_cleanly(tmp_path, monkeypatch):
    launchctl = FakeLaunchctl(loaded=True, lag=4)
    _launchd(tmp_path, monkeypatch, "stop", launchctl)
    assert not launchctl.loaded
    _launchd(tmp_path, monkeypatch, "start", launchctl, plist=False)
    assert launchctl.loaded and launchctl.calls[-1][0] == "kickstart"


def test_launchd_status_reports_not_loaded_cleanly(tmp_path, monkeypatch, capsys):
    launchctl = FakeLaunchctl(loaded=False)
    with pytest.raises(SystemExit) as raised:
        _launchd(tmp_path, monkeypatch, "status", launchctl)
    assert raised.value.code == 3
    assert "not loaded" in capsys.readouterr().out


def test_launchd_status_loaded_succeeds(tmp_path, monkeypatch):
    assert _launchd(tmp_path, monkeypatch, "status", FakeLaunchctl(loaded=True)) == [
        "print"
    ]


def test_launchd_start_requires_installed_plist(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="service install"):
        _launchd(tmp_path, monkeypatch, "start", FakeLaunchctl(), plist=False)


def _recorded_manage(tmp_path, monkeypatch, system, action):
    import platform

    from varde_runner import service

    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    commands = []
    monkeypatch.setattr(
        service, "_run", lambda command, **kwargs: commands.append(command)
    )
    service._manage(action)
    return commands


def test_systemd_stop_and_start(tmp_path, monkeypatch):
    for action in ("stop", "start"):
        commands = _recorded_manage(tmp_path, monkeypatch, "Linux", action)
        assert commands == [["systemctl", "--user", action, "varde-runner.service"]]


def test_launchd_render_sets_working_dir_port_and_relay(tmp_path: Path):
    data = tmp_path / "data"
    value = plistlib.loads(
        render_launchd(
            "/bin/varde-runner", tmp_path, working_dir=data, port=9000, relay=True
        ).encode()
    )
    assert value["ProgramArguments"] == ["/bin/varde-runner", "serve", "--port", "9000"]
    environment = value["EnvironmentVariables"]
    assert environment["VARDE_WORKING_DIR"] == str(data)
    assert environment["VARDE_RUNNER_RELAY"] == "1"


def test_launchd_render_omits_relay_and_never_defaults_to_home(tmp_path: Path):
    value = plistlib.loads(render_launchd("/bin/varde-runner", tmp_path).encode())
    assert "VARDE_RUNNER_RELAY" not in value["EnvironmentVariables"]
    assert "VARDE_WORKING_DIR" not in value["EnvironmentVariables"]


def test_systemd_render_sets_working_dir_port_and_relay(tmp_path: Path):
    data = tmp_path / "data"
    text = render_systemd(home=tmp_path, working_dir=data, port=9000, relay=True)
    assert f'Environment="VARDE_WORKING_DIR={data}"' in text
    assert 'Environment="VARDE_RUNNER_RELAY=1"' in text
    assert '" serve --port 9000\n' in text
    plain = render_systemd(home=tmp_path, working_dir=data)
    assert "VARDE_RUNNER_RELAY" not in plain and '" serve\n' in plain


def test_resolve_working_dir_prefers_option_then_env(tmp_path, monkeypatch):
    from varde_runner.service import resolve_working_dir

    (tmp_path / "env").mkdir()
    (tmp_path / "opt").mkdir()
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "env"))
    assert resolve_working_dir(None) == (tmp_path / "env").resolve()
    assert resolve_working_dir(tmp_path / "opt") == (tmp_path / "opt").resolve()


def test_resolve_working_dir_expands_tilde_and_requires_existing_absolute(
    tmp_path, monkeypatch
):
    from varde_runner.service import resolve_working_dir

    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "data").mkdir()
    assert resolve_working_dir(Path("~/data")) == (tmp_path / "data").resolve()
    with pytest.raises(SystemExit, match="does not exist"):
        resolve_working_dir(Path("~/missing"))
    with pytest.raises(SystemExit, match="absolute"):
        resolve_working_dir(Path("relative/dir"))


def test_resolve_working_dir_refuses_without_either(monkeypatch):
    from varde_runner.service import resolve_working_dir

    monkeypatch.delenv("VARDE_WORKING_DIR", raising=False)
    with pytest.raises(SystemExit, match="--working-dir"):
        resolve_working_dir(None)


def test_install_command_writes_flags_and_reinstall_drops_relay(tmp_path, monkeypatch):
    import platform

    from varde_runner import service

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service, "_run", lambda *a, **k: None)
    monkeypatch.setattr(service.subprocess, "run", FakeLaunchctl().run)
    monkeypatch.setattr(service.time, "sleep", lambda _: None)
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    executable = tmp_path / "varde-runner"
    executable.touch()
    monkeypatch.setattr(service, "installed_runner_path", lambda: str(executable))
    monkeypatch.delenv("VARDE_WORKING_DIR", raising=False)
    plist = tmp_path / "Library/LaunchAgents" / f"{service.LABEL}.plist"
    data = str(tmp_path / "data")
    (tmp_path / "data").mkdir()

    service.run_service(["install", "--working-dir", data, "--enable-relay"])
    first = plistlib.loads(plist.read_bytes())["EnvironmentVariables"]
    assert first["VARDE_WORKING_DIR"] == data and first["VARDE_RUNNER_RELAY"] == "1"

    service.run_service(["install", "--working-dir", data])
    second = plistlib.loads(plist.read_bytes())["EnvironmentVariables"]
    assert "VARDE_RUNNER_RELAY" not in second

    with pytest.raises(SystemExit, match="--working-dir"):
        service.run_service(["install"])


def test_systemd_install_strips_stale_install_keys_from_env_file(tmp_path, monkeypatch):
    import platform

    from varde_runner import service

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    executable = tmp_path / "varde-runner"
    executable.touch()
    monkeypatch.setattr(service, "installed_runner_path", lambda: str(executable))
    env_file = tmp_path / ".config/varde/runner.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text(
        f"VARDE_WORKING_DIR={tmp_path}\nVARDE_RUNNER_RELAY=1\nCUSTOM=kept\n"
    )
    monkeypatch.setattr(service, "_run", lambda *a, **k: None)
    monkeypatch.setattr(
        service.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 0})()
    )
    service._manage("install", working_dir=tmp_path / "data")
    assert env_file.read_text() == "CUSTOM=kept\n"


def test_systemd_quotes_percent_and_dollar(tmp_path):
    text = render_systemd(home=tmp_path, working_dir=tmp_path / "a%b$c")
    assert "a%%b$$c" in text


@pytest.mark.parametrize("port", [0, 70000])
def test_invalid_port_is_refused(tmp_path, port):
    with pytest.raises(SystemExit, match="Invalid port"):
        render_launchd("/bin/varde-runner", tmp_path, port=port)
