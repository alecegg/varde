from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from varde_code.module import register


def test_importing_module_keeps_extract_cli_lazy():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from varde_code.module import register; "
                "assert 'varde_code.cli_extract' not in sys.modules"
            ),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_map_extract_dispatch_uses_extract_cli(monkeypatch, capsys):
    from varde_code import cli_extract

    calls = []
    monkeypatch.setattr(
        cli_extract, "run", lambda argv, io=None: calls.append((argv, io)) or 7
    )
    module = register()
    io = object()

    assert module.run(["map", "extract", "src"], io) == 7
    assert calls == [(["map", "extract", "src"], io)]
    assert module.help("map extract") == cli_extract.help()
    assert capsys.readouterr().out == ""


def test_map_query_dispatch_remains_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "varde_code.cli_query.run", lambda argv, io=None: calls.append((argv, io)) or 5
    )

    assert register().run(["map", "symbols_in_file"], None) == 5
    assert calls == [(["map", "symbols_in_file"], None)]


def test_dispatch_does_not_mutate_caller_argv(monkeypatch):
    monkeypatch.setattr("varde_code.cli_query.run", lambda argv, io=None: 0)
    argv = ["varde", "map", "symbols_in_file"]
    assert register().run(argv) == 0
    assert argv == ["varde", "map", "symbols_in_file"]


def test_legacy_route_prefix_is_split_at_command_boundary(monkeypatch):
    from varde_code import cli_scan

    calls = []
    monkeypatch.setattr(cli_scan, "run", lambda argv, io=None: calls.append(argv) or 0)
    assert register().run(["varde scan", "test"]) == 0
    assert calls == [["scan", "test"]]
