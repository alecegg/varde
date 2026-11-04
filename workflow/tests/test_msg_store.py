import json
from pathlib import Path

from varde_workflow import cli
from varde_workflow.commands import msg_store


def test_store_import_route_parses_source_and_target() -> None:
    args = cli._parser().parse_args(
        ["msg", "store", "import", "--from", "files", "--to", "sqlite"]
    )
    assert args.message_command == "store"
    assert args.store_action == "import"
    assert args.from_store == "files"
    assert args.to_store == "sqlite"


def test_store_verify_repair_route_parses() -> None:
    args = cli._parser().parse_args(["msg", "store", "verify", "--repair-mode"])
    assert args.store_action == "verify"
    assert args.repair_mode


def test_store_verify_force_adopt_route_parses() -> None:
    args = cli._parser().parse_args(
        ["msg", "store", "verify", "--repair-mode", "--force-adopt"]
    )
    assert args.force_adopt


def test_cli_import_runs_end_to_end_and_rejects_same_store(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "messages.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-01-01T00:00:00Z",
                "from": "sender",
                "to": "reader",
                "kind": "info",
                "text": "hello",
                "id": "m-1234abcd",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert cli.run(["msg", "store", "import", "--from", "files", "--to", "sqlite"]) == 0
    output = capsys.readouterr().out
    assert "messages 1->1" in output
    assert "ids" in output
    assert "unread" in output
    assert "concluded" in output
    assert cli.run(["msg", "store", "import", "--from", "files", "--to", "files"]) == 1


def test_msg_store_run_returns_nonzero_for_real_mismatch(
    tmp_path: Path, capsys
) -> None:
    args = cli._parser().parse_args(["msg", "store", "verify"])
    assert msg_store.run(args, tmp_path) == 1
    assert "store is absent" in capsys.readouterr().err


def test_store_mode_help_snapshot_exists(capsys) -> None:
    assert cli.run(["msg", "store", "mode", "--help"]) == 0
    output = capsys.readouterr().out

    assert "Usage: varde msg store mode" in output
    assert "mirror-sqlite" in output
    assert cli.run(["msg", "store", "mode", "-h"]) == 0
    assert "Usage: varde msg store mode" in capsys.readouterr().out


def test_repair_mode_returns_repair_status_without_unrelated_parity_check(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    args = cli._parser().parse_args(["msg", "store", "verify", "--repair-mode"])
    monkeypatch.setattr(
        msg_store,
        "repair_mode",
        lambda _working, *, force_adopt=False: "repair complete",
    )
    monkeypatch.setattr(msg_store, "read_store_mode", lambda _working: object())
    monkeypatch.setattr(
        msg_store,
        "verify",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected parity check")),
    )

    assert msg_store.run(args, tmp_path) == 0
    assert capsys.readouterr().out.strip() == "repair complete"


def test_repair_mode_forwards_force_adopt(tmp_path: Path, monkeypatch, capsys) -> None:
    args = cli._parser().parse_args(
        ["msg", "store", "verify", "--repair-mode", "--force-adopt"]
    )
    calls: list[bool] = []
    monkeypatch.setattr(
        msg_store,
        "repair_mode",
        lambda _working, *, force_adopt=False: (
            calls.append(force_adopt) or "force-adopt complete"
        ),
    )
    monkeypatch.setattr(msg_store, "read_store_mode", lambda _working: object())

    assert msg_store.run(args, tmp_path) == 0
    assert calls == [True]
    assert capsys.readouterr().out.strip() == "force-adopt complete"


def test_repair_mode_returns_nonzero_when_repair_leaves_no_marker(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    args = cli._parser().parse_args(["msg", "store", "verify", "--repair-mode"])
    monkeypatch.setattr(
        msg_store,
        "repair_mode",
        lambda _working, *, force_adopt=False: "repair incomplete",
    )
    monkeypatch.setattr(msg_store, "read_store_mode", lambda _working: None)

    assert msg_store.run(args, tmp_path) == 1
    assert "did not produce a valid marker" in capsys.readouterr().err
