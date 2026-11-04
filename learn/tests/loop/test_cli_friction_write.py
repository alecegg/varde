from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace

from varde_learn.loop import cli_friction

HELP_PATHS = (
    ("friction", "friction.txt"),
    ("friction list", "friction/list.txt"),
    ("friction add", "friction/add.txt"),
    ("friction show", "friction/show.txt"),
    ("friction set-status", "friction/set-status.txt"),
    ("friction export", "friction/export.txt"),
    ("friction import", "friction/import.txt"),
    ("adopt", "adopt.txt"),
    ("adopt record", "adopt/record.txt"),
    ("adopt recurrence", "adopt/recurrence.txt"),
)


def test_cli_help_shows_usage_for_commands():
    for command, _relative in HELP_PATHS:
        output = StringIO()
        assert (
            cli_friction.run(
                command.split() + ["--help"],
                SimpleNamespace(stdout=output, stderr=StringIO()),
            )
            == 0
        )
        assert "Usage:" in output.getvalue()


def test_cli_shell_errors_return_usage_status():
    for args in (
        ["friction"],
        ["adopt"],
        ["friction", "bogus"],
        ["friction", "list", "--rep", "/repo"],
        ["friction", "list", "--repo", "/repo"],
    ):
        output = SimpleNamespace(stdout=StringIO(), stderr=StringIO())
        assert cli_friction.run(list(args), output) == 2
        assert output.stdout.getvalue() == ""


def test_unknown_subcommand_help_returns_usage_error():
    for args in (
        ["friction", "archive", "--help"],
        ["friction", "bogus", "-h"],
        ["adopt", "archive", "--help"],
    ):
        output = SimpleNamespace(stdout=StringIO(), stderr=StringIO())

        assert cli_friction.run(args, output) == 2
        assert output.stdout.getvalue() == ""
        assert "error: unrecognized subcommand '" in output.stderr.getvalue()


def test_friction_add_short_help_shows_usage():
    output = SimpleNamespace(stdout=StringIO(), stderr=StringIO())
    assert cli_friction.run(["friction", "add", "-h"], output) == 0
    assert "Usage:" in output.stdout.getvalue()


def test_add_and_set_status_emit_json_envelopes(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "store"))
    monkeypatch.chdir(tmp_path)
    add_out = StringIO()
    add_io = SimpleNamespace(stdout=add_out, stderr=StringIO(), stdin=StringIO())
    assert (
        cli_friction.run(
            [
                "friction",
                "add",
                "--source",
                "pytest",
                "--title",
                "Store write",
                "--text",
                "evidence",
                "--json",
            ],
            add_io,
        )
        == 0
    )
    added = json.loads(add_out.getvalue())
    assert added["data"]["id"] > 0
    assert added["data"]["similar"] == []

    status_out = StringIO()
    status_io = SimpleNamespace(stdout=status_out, stderr=StringIO(), stdin=StringIO())
    assert (
        cli_friction.run(
            [
                "friction",
                "set-status",
                "--reason",
                "fixed",
                str(added["data"]["id"]),
                "resolved",
                "--json",
            ],
            status_io,
        )
        == 0
    )
    status = json.loads(status_out.getvalue())
    assert status["data"] == {"id": added["data"]["id"], "status": "resolved"}


def test_multi_status_and_add_confirmation_through_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "store"))
    monkeypatch.chdir(tmp_path)
    io = SimpleNamespace(stdout=StringIO(), stderr=StringIO(), stdin=StringIO())
    ids = []
    for title in ("First", "Second"):
        io.stdout = StringIO()
        assert (
            cli_friction.run(
                ["add", "--source", "test", "--title", title, "--text", "evidence"], io
            )
            == 0
        )
        confirmation = io.stdout.getvalue()
        assert confirmation.count("\n") == 1
        ids.append(int(confirmation.split()[-1][:-1]))
    io.stdout = StringIO()
    assert (
        cli_friction.run(
            ["set-status", "--reason", "fixed", *map(str, ids), "resolved"], io
        )
        == 0
    )
    assert io.stdout.getvalue().splitlines() == [
        f"{item_id} [resolved]" for item_id in ids
    ]


def test_tags_add_filter_existing_and_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "store"))
    monkeypatch.chdir(tmp_path)
    io = SimpleNamespace(stdout=StringIO(), stderr=StringIO(), stdin=StringIO())
    assert (
        cli_friction.run(
            [
                "add",
                "--source",
                "test",
                "--title",
                "Tagged",
                "--text",
                "evidence",
                "--tag",
                "speed",
                "--tag",
                "token",
                "--json",
            ],
            io,
        )
        == 0
    )
    item_id = json.loads(io.stdout.getvalue())["data"]["id"]
    io.stdout = StringIO()
    assert (
        cli_friction.run(
            ["add", "--item", str(item_id), "--text", "more", "--tag", "latency"], io
        )
        == 0
    )
    io.stdout = StringIO()
    assert cli_friction.run(["list", "--tag", "latency", "--json"], io) == 0
    item = json.loads(io.stdout.getvalue())["data"]["items"][0]
    assert item["tags"] == ["latency", "speed", "token"]
    io.stdout = StringIO()
    assert cli_friction.run(["show", str(item_id)], io) == 0
    assert "Tags: latency, speed, token" in io.stdout.getvalue()
    io.stdout = StringIO()
    io.stderr = StringIO()
    assert (
        cli_friction.run(
            [
                "add",
                "--source",
                "test",
                "--title",
                "Bad",
                "--text",
                "evidence",
                "--tag",
                "Bad",
            ],
            io,
        )
        == 2
    )
    assert "invalid tag" in io.stderr.getvalue()


def test_import_missing_directory_returns_error(tmp_path, monkeypatch):
    from varde_learn.loop.cli_friction_write import run_import_command

    monkeypatch.chdir(tmp_path)
    output = SimpleNamespace(stdout=StringIO(), stderr=StringIO())

    assert (
        run_import_command(
            {"directory": "./missing", "repository": str(tmp_path), "json": True},
            output,
        )
        == 2
    )
    payload = json.loads(output.stderr.getvalue())
    assert "could not inspect import directory" in payload["data"]["error"]["message"]
