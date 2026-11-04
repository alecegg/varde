from __future__ import annotations

from pathlib import Path

from varde_core.io import Io
from varde_toz.module import Module

PACKAGE = Path(__file__).parent


def test_module_help_has_usage_and_unknown_command_has_error(capsys) -> None:
    module = Module()
    assert module.name == "toz"
    assert module.run(["run", "--help"], Io()) == 0
    assert "Usage: varde run run" in capsys.readouterr().out
    try:
        module.run(["unknown-command"], Io())
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("unknown command should return the usage error exit code")
    assert "unknown command" in capsys.readouterr().err


def test_module_help_routes_start_with_usage() -> None:
    module = Module()
    routes = [
        path.stem.replace("_", " ")
        for path in (PACKAGE.parent / "src/varde_toz/help").glob("*.txt")
    ]
    for route in routes:
        assert any(
            line.startswith("Usage:") for line in module.help(route).splitlines()
        ), route
