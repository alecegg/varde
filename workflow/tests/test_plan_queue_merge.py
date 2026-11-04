from __future__ import annotations

from varde_workflow.cli import _parser, run


def test_merge_and_rollback_commands_are_registered() -> None:
    merge = _parser().parse_args(["plan", "queue", "merge-role-inbox"])
    rollback = _parser().parse_args(["plan", "queue", "rollback-role-inbox"])

    assert merge.queue_action == "merge-role-inbox"
    assert rollback.queue_action == "rollback-role-inbox"


def test_merge_command_help_snapshot(capsys) -> None:
    assert run(["plan", "queue", "merge-role-inbox", "--help"]) == 0
    assert "Stop the runner first" in capsys.readouterr().out


def test_rollback_command_help_snapshot(capsys) -> None:
    assert run(["plan", "queue", "rollback-role-inbox", "--help"]) == 0
    assert "restores the previous queue marker" in capsys.readouterr().out
