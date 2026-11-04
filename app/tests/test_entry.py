import subprocess
import sys
from types import SimpleNamespace

import pytest
from varde import cli, discovery


class FakeModule:
    name = "fake"

    def __init__(self, result=7):
        self.result = result

    def run(self, argv, io):
        print(f"ran {argv!r} with {io!r}")
        return self.result

    def help(self, path):
        return f"help:{path}"


def test_discovery_loads_registered_factories(monkeypatch):
    module = FakeModule()
    monkeypatch.setattr(
        discovery,
        "entry_points",
        lambda **kwargs: [SimpleNamespace(name="fake", load=lambda: lambda: module)],
    )

    assert discovery.discover_modules() == {"fake": module}


def test_discovery_rejects_duplicate_module_names(monkeypatch):
    monkeypatch.setattr(
        discovery,
        "entry_points",
        lambda **kwargs: [
            SimpleNamespace(name=entry, load=lambda: FakeModule) for entry in ("a", "b")
        ],
    )

    with pytest.raises(ValueError, match="duplicate"):
        discovery.discover_modules()


def test_cli_import_defers_router_until_routing():
    code = "import sys; import varde.cli; assert 'varde.router' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603 - Verifies import behavior in a clean interpreter process.


def test_main_routes_and_preserves_exit_code(monkeypatch, capsys):
    module = FakeModule(19)
    monkeypatch.setattr("varde.discovery.discover_modules", lambda: {"code": module})
    monkeypatch.setattr("varde.io.create_io", lambda: "io")
    monkeypatch.setattr(
        cli, "signal", SimpleNamespace(SIGPIPE=1, SIG_IGN=0, signal=lambda *a: None)
    )

    assert cli.main(["map", "nav_map"]) == 19
    assert capsys.readouterr().out == "ran ['varde map', 'nav_map'] with 'io'\n"


def test_docs_help_is_forwarded_to_module_run(monkeypatch, capsys):
    module = FakeModule()
    monkeypatch.setattr("varde.discovery.discover_modules", lambda: {"learn": module})
    monkeypatch.setattr(
        cli, "signal", SimpleNamespace(SIGPIPE=1, SIG_IGN=0, signal=lambda *a: None)
    )

    assert cli.main(["learn", "docs", "spec", "--help"]) == 7
    assert "ran ['docs', 'spec', '--help']" in capsys.readouterr().out


def test_unknown_command_exits_with_usage_error(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "signal", SimpleNamespace(SIGPIPE=1, SIG_IGN=0, signal=lambda *a: None)
    )

    assert cli.main(["nonsense"]) == 2
    assert capsys.readouterr().err == (
        "error: unrecognized subcommand 'nonsense'\n\n"
        "Usage: varde [OPTIONS] <COMMAND>\n\n"
        "For more information, try '--help'.\n"
    )


def test_closed_stdout_exits_quietly(monkeypatch):
    monkeypatch.setattr(
        cli, "signal", SimpleNamespace(SIGPIPE=1, SIG_IGN=0, signal=lambda *a: None)
    )

    class Closed:
        def write(self, value):
            raise BrokenPipeError

        def close(self):
            pass

    monkeypatch.setattr(cli.sys, "stdout", Closed())
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: Closed())
    assert cli.main(["--help"]) == 0
