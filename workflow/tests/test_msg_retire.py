from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from varde_workflow.commands.msg_retire import run


def test_retire_rejects_unreviewed_address_list(tmp_path, capsys) -> None:
    assert run(Namespace(addresses=["main"]), tmp_path) == 1
    assert "use --dry-run" in capsys.readouterr().err


def test_retire_command_is_registered_in_cli() -> None:
    from varde_workflow.cli import _parser

    args = _parser().parse_args(["msg", "retire", "--apply", "/audit/list.json"])
    assert args.message_command == "retire"
    assert args.apply == Path("/audit/list.json")

    dry_run = _parser().parse_args(["msg", "retire", "--dry-run", "/audit"])
    assert dry_run.dry_run == Path("/audit")
    assert dry_run.min_age_days == 30

    younger = _parser().parse_args(
        ["msg", "retire", "--dry-run", "/audit", "--min-age-days", "14"]
    )
    assert younger.min_age_days == 14
    try:
        _parser().parse_args(
            ["msg", "retire", "--dry-run", "/audit", "--min-age-days", "0"]
        )
    except ValueError as exc:
        assert "greater than zero" in str(exc)
    else:
        raise AssertionError("minimum age below one day must be rejected")

    mode = _parser().parse_args(["msg", "store", "mode", "sqlite"])
    assert mode.store_action == "mode"


def test_retire_help_snapshot_exists(capsys) -> None:
    from varde_workflow.cli import run

    assert run(["msg", "retire", "--help"]) == 0
    output = capsys.readouterr().out

    assert "Usage: varde msg retire" in output
    assert "--dry-run" in output
    assert "--min-age-days" in output
    assert "--restore" in output
    assert run(["msg", "retire", "-h"]) == 0
    assert "Usage: varde msg retire" in capsys.readouterr().out


def test_retire_age_override_is_recorded_and_used_on_apply(tmp_path: Path) -> None:
    import json
    from datetime import UTC, datetime, timedelta

    from varde_workflow import mail_retirement
    from varde_workflow.inbox import append_message

    working = tmp_path / "working"
    working.mkdir()
    append_message(
        "main",
        "python-port-two-weeks-old",
        "info",
        "stale backlog",
        working=working,
        now=datetime.now(UTC) - timedelta(days=14),
    )

    default = mail_retirement.build_dry_run(working)
    assert default["addresses"] == []

    dry_run = mail_retirement.write_dry_run(working, tmp_path / "audit", 14)
    payload = json.loads(dry_run.read_text(encoding="utf-8"))
    assert payload["min_age_days"] == 14
    assert payload["addresses"] == ["python-port-two-weeks-old"]

    result = mail_retirement.apply_dry_run(working, dry_run)
    audit = json.loads(Path(result["audit"]).read_text(encoding="utf-8"))
    assert audit["min_age_days"] == 14
