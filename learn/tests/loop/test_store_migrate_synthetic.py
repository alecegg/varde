"""Synthetic learn root: ``varde learn store`` migrate, verify and retire per domain."""

from __future__ import annotations

import io
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_data.friction import open_friction
from varde_data.learn_store_mode import read_learn_mode
from varde_learn.loop.cli_friction_read import run_list
from varde_learn.module import register

GOLDEN = Path(__file__).parent / "golden" / "friction"


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store = tmp_path / "learn"
    store.mkdir()
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    return store


def _store(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict]:
    code = register().run(["learn", "store", *args, "--json"])
    return code, json.loads(capsys.readouterr().out)["data"]


def _list_json() -> dict:
    output = SimpleNamespace(stdout=io.StringIO(), stderr=io.StringIO())
    assert run_list({"json": True, "limit": 1000}, output) == 0
    return json.loads(output.stdout.getvalue())


def _friction_root(root: Path) -> None:
    shutil.copyfile(GOLDEN / "friction.jsonl", root / "friction.jsonl")
    open_friction(root, "files").list_items()  # builds the legacy learn.db index


def test_friction_migrates_verifies_and_retires(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _friction_root(root)
    log_before = (root / "friction.jsonl").read_bytes()
    listing_before = _list_json()
    assert (root / "learn.db").exists()

    code, data = _store(capsys, "migrate", "--domain", "friction", "--dry-run")
    assert code == 0 and data["would_import"] > 0
    assert not (root / "learn.sqlite3").exists()

    code, data = _store(capsys, "migrate", "--domain", "friction")
    assert code == 0 and data["ok"] is True
    assert read_learn_mode(root).friction == "sqlite"
    assert (root / "friction.jsonl").read_bytes() == log_before
    assert _list_json() == listing_before

    code, data = _store(capsys, "verify", "--domain", "friction")
    assert code == 0 and data["ok"] is True and data["problems"] == []

    code, data = _store(capsys, "status")
    friction = data["domains"]["friction"]
    assert friction["mode"] == "sqlite"
    assert friction["rows"] == len(log_before.splitlines())
    assert friction["files_present"] is True

    code, data = _store(capsys, "retire", "--domain", "friction")
    assert code == 0 and data["retired"] is True
    for name in ("friction.jsonl", "learn.db", "learn.db.init.lock"):
        assert not (root / name).exists()
    assert _list_json() == listing_before
    assert _store(capsys, "verify", "--domain", "friction")[1]["ok"] is True


def test_migrate_is_idempotent_and_leaves_other_domains(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _friction_root(root)
    _store(capsys, "migrate", "--domain", "friction")
    with closing(sqlite3.connect(root / "learn.sqlite3")) as db:
        rows = db.execute("SELECT COUNT(*) FROM friction_events").fetchone()[0]
    record = read_learn_mode(root)
    assert (record.ledger, record.calls) == ("files", "files")
    assert rows == len(
        [line for line in (root / "friction.jsonl").read_text().splitlines() if line]
    )


def test_verify_reports_a_diverged_sqlite_log(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _friction_root(root)
    _store(capsys, "migrate", "--domain", "friction")
    with closing(sqlite3.connect(root / "learn.sqlite3")) as db, db:
        db.execute(
            "DELETE FROM friction_events "
            "WHERE seq = (SELECT MAX(seq) FROM friction_events)"
        )

    code, data = _store(capsys, "verify", "--domain", "friction")

    assert code == 1 and data["ok"] is False
    assert data["problems"]
    code, data = _store(capsys, "retire", "--domain", "friction")
    assert code == 1 and data["retired"] is False
    assert (root / "friction.jsonl").exists()


def test_events_appended_after_the_flip_do_not_block_verify_or_retire(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from varde_data.repos.friction import FrictionAddRequest

    _friction_root(root)
    _store(capsys, "migrate", "--domain", "friction")
    assert (root / "learn.sqlite3.friction-backup").is_file()
    assert not (root / "learn.sqlite3.friction-backup.tmp").exists()
    open_friction(root).add(
        FrictionAddRequest("Added later", "pytest", "again", "/work", "/repo")
    )

    code, data = _store(capsys, "verify", "--domain", "friction")
    assert code == 0 and data["ok"] is True
    assert data["stored_events"] > data["events"]

    code, data = _store(capsys, "retire", "--domain", "friction")
    assert code == 0 and data["retired"] is True
    assert not (root / "friction.jsonl").exists()
    slugs = [item["slug"] for item in _list_json()["data"]["items"]]
    assert "added-later" in slugs


def test_unreadable_learn_db_fails_migrate_and_keeps_everything(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _friction_root(root)
    (root / "learn.db-wal").unlink(missing_ok=True)
    (root / "learn.db").write_bytes(b"not a database" * 100)

    code, data = _store(capsys, "migrate", "--domain", "friction")

    assert code == 1 and data["ok"] is False
    assert "unreadable" in data["problems"][0]
    assert read_learn_mode(root).friction == "files"
    assert (root / "learn.db").exists()


def test_stale_learn_db_fails_migrate_with_a_refresh_hint(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _friction_root(root)
    with (root / "friction.jsonl").open("a") as stream:
        stream.write("\n")
        stream.write((GOLDEN / "friction.jsonl").read_text().splitlines()[0] + "\n")

    code, data = _store(capsys, "migrate", "--domain", "friction", "--dry-run")

    assert code == 1 and data["ok"] is False
    assert "out of date" in data["problems"][0]


def test_without_learn_db_ids_and_slugs_match_the_files_backend(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copyfile(GOLDEN / "friction.jsonl", root / "friction.jsonl")
    reference = root.parent / "reference"
    reference.mkdir()
    shutil.copyfile(GOLDEN / "friction.jsonl", reference / "friction.jsonl")
    expected = [
        (item.slug, item.event_id)
        for item in open_friction(reference, "files").list_items().items
    ]
    assert not (root / "learn.db").exists()

    code, data = _store(capsys, "migrate", "--domain", "friction")

    assert code == 0 and data["ok"] is True
    actual = [
        (item.slug, item.event_id) for item in open_friction(root).list_items().items
    ]
    assert actual == expected


def test_gitignore_is_extended_once_and_never_created(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _friction_root(root)
    (root / ".gitignore").write_text("learn.db*")
    _store(capsys, "migrate", "--domain", "friction")
    text = (root / ".gitignore").read_text()
    for pattern in ("learn.sqlite3*", "store-mode.json", "store-mode.lock"):
        assert text.splitlines().count(pattern) == 1
    assert text.startswith("learn.db*\n")


def test_no_gitignore_is_created_by_a_flip(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copyfile(GOLDEN / "friction.jsonl", root / "friction.jsonl")
    (root / ".gitignore").unlink(missing_ok=True)
    _store(capsys, "migrate", "--domain", "friction")
    assert not (root / ".gitignore").exists()
