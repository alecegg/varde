import sys
from pathlib import Path

import pytest
from varde_serve.__main__ import COMMANDS, main
from varde_serve.commands import status


def test_unknown_or_extra_arguments_are_usage_errors(capsys) -> None:
    assert main(["bogus"]) == 2
    assert main(["stop", "now"]) == 2
    assert "usage" in capsys.readouterr().err


def test_command_table_is_exactly_the_approved_set() -> None:
    assert set(COMMANDS) == {"start", "stop", "status", "mcp", "daemon"}


def test_status_when_stopped_prints_token_path_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert status(tmp_path) == 0
    out = capsys.readouterr().out
    assert "not running" in out
    assert str(tmp_path / "serve" / "token") in out
    assert sys.version  # keep import used


def test_status_never_prints_the_token_value(
    served_factory, capsys: pytest.CaptureFixture[str]
) -> None:
    served = served_factory()
    capsys.readouterr()
    assert status(served.config_dir) == 0
    out = capsys.readouterr().out
    assert "running" in out
    assert served.tokens.human not in out
    assert served.tokens.mcp not in out
