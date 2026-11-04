from __future__ import annotations

import pytest
from varde import cli


@pytest.fixture(autouse=True)
def isolated_learn_store(monkeypatch, tmp_path):
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "learn"))


@pytest.fixture
def rows(monkeypatch):
    for name in (
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_SESSION_ID",
        "CODEX_THREAD_ID",
        "VARDE_TOZ_SESSION",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        cli,
        "signal",
        type(
            "Signal",
            (),
            {"SIGPIPE": 1, "SIG_IGN": 0, "signal": staticmethod(lambda *args: None)},
        ),
    )
    module = type("Module", (), {"run": lambda self, argv, io: 0})()
    monkeypatch.setattr(
        cli,
        "_discover_modules",
        lambda: {"code": module, "learn": module, "workflow": module},
    )
    monkeypatch.setattr(cli, "_create_io", lambda: None)
    monkeypatch.setattr(
        "varde.setup.dispatch.run_setup_route",
        lambda args: 0 if args[:2] == ["setup", "watch"] else None,
    )
    recorded = []
    monkeypatch.setattr(
        "varde_learn.loop.calls.append_call", lambda row: recorded.append(row) or True
    )
    return recorded


@pytest.mark.parametrize(
    "args",
    [
        ["setup", "watch"],
        ["setup", "watch", "--ensure"],
        ["setup", "watch", "--stop"],
        ["plan", "watch"],
        ["plan", "watch", "--once"],
        ["learn", "sessions", "fire", "g"],
    ],
)
def test_excluded_commands_record_no_row(rows, args):
    cli.main(args)
    assert rows == []


def test_control_command_is_still_recorded(rows):
    assert cli.main(["map", "nav_map"]) == 0
    assert [row["command"] for row in rows] == ["map"]
