from __future__ import annotations

import json
from typing import cast

import pytest
from varde_code import cli_query
from varde_code.module import register
from varde_core.io import Io as OutputIo

# The registered mode names are the enumeration source for the help snapshot
# check; every assertion below reads the CLI's public output.
MODE_HELP_FILES = sorted(cli_query._MODE_HELP.items())


def test_query_cli_dispatches_modes_and_passes_capture(monkeypatch, capsys):
    calls = []

    def dispatch(mode, value, capture=None):
        calls.append((mode, value, capture))
        return {"ok": True, "data": {"mode": mode}}

    class Io:
        capture = object()

    monkeypatch.setattr(cli_query, "dispatch", dispatch)

    status = cli_query.run(
        ["find_pattern", "--json", '{"pattern":"f($X)"}'], cast("OutputIo", Io())
    )

    assert status == 0
    assert calls == [("find_pattern", {"pattern": "f($X)"}, Io.capture)]
    assert json.loads(capsys.readouterr().out) == {
        "ok": True,
        "data": {"mode": "find_pattern"},
    }


def test_nav_map_text_uses_text_renderer(monkeypatch, capsys):
    monkeypatch.setattr(
        cli_query,
        "dispatch",
        lambda mode, value, capture=None: {"ok": True, "data": {}},
    )
    monkeypatch.setattr(
        cli_query,
        "nav_map_text",
        lambda result, with_knowledge: f"rendered:{with_knowledge}",
    )

    assert (
        cli_query.run(
            [
                "nav_map",
                "--json",
                '{"repoRoot":"."}',
                "--format",
                "text",
                "--with-project-knowledge",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == "rendered:True\n"


def test_map_help_lists_every_registered_command(capsys):
    assert cli_query.run(["--help"]) == 0
    help_output = capsys.readouterr().out

    for mode, _ in MODE_HELP_FILES:
        assert mode in help_output


@pytest.mark.parametrize(
    ("mode", "filename"), MODE_HELP_FILES, ids=[mode for mode, _ in MODE_HELP_FILES]
)
def test_every_command_help_topic_prints_its_snapshot(mode, filename, capsys):
    assert cli_query.run([mode, "--help"]) == 0
    output = capsys.readouterr().out

    assert output.strip()
    assert output == (cli_query.HELP_DIR / filename).read_text(encoding="utf-8")


def test_registered_module_routes_map_commands(capsys):
    module = register()

    assert module.run(["map", "--help"]) == 0
    assert capsys.readouterr().out == (cli_query.HELP_DIR / "map.txt").read_text(
        encoding="utf-8"
    )

    assert module.run(["status"]) == 2
    assert capsys.readouterr().err == "code: module stub\n"


def test_query_cli_strips_internal_fields_from_nested_results(monkeypatch, capsys):
    monkeypatch.setattr(
        cli_query,
        "dispatch",
        lambda mode, value, capture=None: {
            "schema_version": 1,
            "envelope_version": 1,
            "data": [{"envelope_version": 1, "ok": True}],
        },
    )

    assert cli_query.run(["nav_map", "--json", "{}"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "data": [{"ok": True}],
    }
