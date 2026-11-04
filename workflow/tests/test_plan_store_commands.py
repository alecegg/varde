from __future__ import annotations

import json
from pathlib import Path

from varde_workflow import cli


def _working(tmp_path: Path, monkeypatch) -> Path:
    working = tmp_path / "memory"
    plan = working / "plans" / "sample"
    plan.mkdir(parents=True)
    (plan / "plan.md").write_text(
        "---\ntype: plan\nstatus: active\n---\n", encoding="utf-8"
    )
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(working)
    return working


def test_store_help_lists_all_operations(capsys) -> None:
    assert cli.run(["plan", "store", "--help"]) == 0
    output = capsys.readouterr().out
    for action in (
        "status",
        "migrate",
        "export",
        "import",
        "backup",
        "restore",
        "rollback",
        "verify",
    ):
        assert action in output


def test_store_status_reports_markdown_mode_without_database(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    working = _working(tmp_path, monkeypatch)

    assert cli.run(["plan", "store", "status", "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["data"]["mode"] == "markdown"
    assert result["data"]["exists"] is False
    assert not (working / ".cache/data/queue.sqlite3").exists()


def test_migrate_dry_run_does_not_create_database(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    working = _working(tmp_path, monkeypatch)

    assert cli.run(["plan", "store", "migrate", "--dry-run", "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["data"]["dry_run"] is True
    assert not (working / ".cache/data/queue.sqlite3").exists()


def test_import_reads_markdown_state_without_flipping_store_mode(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    working = _working(tmp_path, monkeypatch)
    queue = working / "plans" / "sample" / "queue.md"
    queue.write_text("# Queue\n\n| id | state |\n|---|---|\n| item | queued |\n")

    assert cli.run(["plan", "store", "import", "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["data"]["queues"][0]["added"] == 1
    assert result["data"]["plans_imported"] == [str(queue.parent)]


def test_migrate_and_rollback_create_verified_backups(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _working(tmp_path, monkeypatch)

    assert cli.run(["plan", "store", "migrate", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["backup"] is None

    assert cli.run(["plan", "store", "migrate", "--json"]) == 0
    migration = json.loads(capsys.readouterr().out)["data"]
    assert Path(migration["backup"]).is_file()

    assert cli.run(["plan", "store", "rollback", "--json"]) == 0
    rollback = json.loads(capsys.readouterr().out)["data"]
    assert Path(rollback["backup"]).is_file()


def test_export_dry_run_and_export_preserve_queue_markdown(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    working = _working(tmp_path, monkeypatch)
    queue = working / "plans" / "sample" / "queue.md"
    queue_text = "# Queue\n\n| id | state |\n|---|---|\n| item | queued |\n"
    queue.write_text(queue_text, encoding="utf-8")
    assert cli.run(["plan", "store", "migrate"]) == 0
    capsys.readouterr()

    queue.write_text(queue_text.replace("queued", "building"), encoding="utf-8")
    assert cli.run(["plan", "store", "export", "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["dry_run"] is True
    assert "building" in queue.read_text(encoding="utf-8")

    assert cli.run(["plan", "store", "export", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["data"]["files"]
    assert "building" in queue.read_text(encoding="utf-8")
