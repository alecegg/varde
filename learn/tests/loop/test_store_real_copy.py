"""Migrate, verify and retire each domain of a copy of the real learn root.

The synthetic tests always run the same scenario on generated data. The
real-copy tests are opt-in: set ``VARDE_LEARN_REAL_COPY`` to a copy of
``~/.config/varde/learn``; without it they skip. They work on a second copy
inside the temp directory, so the named copy is never modified.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from varde_data.calls import open_calls
from varde_data.calls_store import connect, has_blob_layout
from varde_data.friction import open_friction
from varde_data.learn_store_mode import learn_db_path, read_learn_mode
from varde_data.ledger import open_ledger
from varde_data.repos.friction import FrictionAddRequest
from varde_learn.loop import calls
from varde_learn.module import register

GOLDEN = Path(__file__).parent / "golden" / "friction"
DOMAINS = ["friction", "ledger", "calls"]


def _synthetic_root(root: Path) -> None:
    shutil.copyfile(GOLDEN / "friction.jsonl", root / "friction.jsonl")
    ledger = open_ledger(root, "files")
    for index in range(20):
        ledger.mark("codex", f"s{index}", "2026-01-01T00:00:00Z", "summary")
    ledger.write_digest(date(2026, 1, 1), "digest", [{"slug": "a"}])
    calls = open_calls(root, "files")
    for index in range(200):
        calls.append(
            {
                "ts": f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}Z",
                "command": "plan status",
                "status": "failure" if index % 7 == 0 else "success",
                "duration_s": 0.1,
                "session": f"s{index % 5}",
            }
        )


@pytest.fixture
def synthetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = tmp_path / "learn"
    work.mkdir()
    monkeypatch.setenv("VARDE_LEARN_STORE", str(work))
    _synthetic_root(work)
    return work


@pytest.fixture
def copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    named = os.environ.get("VARDE_LEARN_REAL_COPY")
    if not named:
        pytest.skip(
            "opt-in: set VARDE_LEARN_REAL_COPY to a copy of the real learn root"
        )
    source = Path(named).expanduser()
    assert source.is_dir(), f"{source} is not a directory"
    assert source.resolve() != (Path.home() / ".config/varde/learn").resolve(), (
        "VARDE_LEARN_REAL_COPY must be a copy, not the real store"
    )
    work = tmp_path / "learn"
    shutil.copytree(source, work)
    monkeypatch.setenv("VARDE_LEARN_STORE", str(work))
    return work


def _store(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict, float]:
    started = time.perf_counter()
    code = register().run(["learn", "store", *args, "--json"])
    elapsed = time.perf_counter() - started
    return code, json.loads(capsys.readouterr().out)["data"], elapsed


def _post_flip_write(root: Path, domain: str) -> None:
    if domain == "friction":
        open_friction(root).add(
            FrictionAddRequest("Post flip", "session", "after", "/work", "/repo")
        )
    elif domain == "ledger":
        ledger = open_ledger(root)
        ledger.mark("codex", "post-flip", "2026-10-30T00:00:00Z", "after")
        ledger.write_digest(date(2026, 10, 30), "after", [])
    else:
        open_calls(root).append(
            {
                "ts": "2026-10-30T00:00:00Z",
                "command": "plan status",
                "status": "success",
                "duration_s": 0.1,
            }
        )


@pytest.mark.parametrize("domain", DOMAINS)
def test_synthetic_domain_migrates_verifies_and_retires(
    synthetic: Path, capsys: pytest.CaptureFixture[str], domain: str
) -> None:
    _exercise(synthetic, capsys, domain)


@pytest.mark.parametrize("domain", DOMAINS)
def test_real_copy_domain_migrates_verifies_and_retires(
    copy: Path, capsys: pytest.CaptureFixture[str], domain: str
) -> None:
    _exercise(copy, capsys, domain)


def _exercise(copy: Path, capsys: pytest.CaptureFixture[str], domain: str) -> None:
    if domain == "friction":
        open_friction(copy, "files").list_items()  # build or refresh learn.db
    before = _store(capsys, "status")[1]["domains"][domain]
    assert before["mode"] == "files"

    code, data, migrate_s = _store(capsys, "migrate", "--domain", domain)
    assert code == 0 and data["ok"] is True, data
    assert read_learn_mode(copy).mode(domain) == "sqlite"

    code, data, verify_s = _store(capsys, "verify", "--domain", domain)
    assert code == 0 and data["ok"] is True, data

    started = time.perf_counter()
    _post_flip_write(copy, domain)
    write_s = time.perf_counter() - started
    assert _store(capsys, "verify", "--domain", domain)[1]["ok"] is True

    after = _store(capsys, "status")[1]["domains"][domain]
    assert after["rows"] >= before["rows"]

    code, data, retire_s = _store(capsys, "retire", "--domain", domain)
    assert code == 0 and data["retired"] is True, data
    assert _store(capsys, "verify", "--domain", domain)[1]["ok"] is True
    print(
        f"real-copy {domain}: rows={before['rows']} migrate={migrate_s:.2f}s "
        f"verify={verify_s:.2f}s first-write={write_s * 1000:.1f}ms "
        f"retire={retire_s:.2f}s"
    )


def _v1_report(path: Path) -> str:
    """Rank the valid rows of a v1 database straight from its JSON blobs."""
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
        blobs = [
            json.loads(text)
            for (text,) in db.execute("SELECT row FROM cli_calls ORDER BY id")
        ]
    rows = [row for row in blobs if calls._valid_row(row)]
    return json.dumps(calls.rank_commands(rows), sort_keys=True)


def test_real_copy_calls_layout_upgrade_keeps_output_and_shrinks_the_file(
    copy: Path,
) -> None:
    database = learn_db_path(copy)
    with closing(sqlite3.connect(database)) as db:
        if not has_blob_layout(db):
            pytest.skip("the copied store already has the typed calls layout")
    before_size = database.stat().st_size
    before = _v1_report(database)

    started = time.perf_counter()
    connect(copy).close()  # any open runs the upgrade, backup and VACUUM
    upgrade_s = time.perf_counter() - started

    after = json.dumps(calls.rank_commands(calls.read_calls_strict()), sort_keys=True)
    after_size = database.stat().st_size
    print(
        f"real-copy calls_layout: upgrade={upgrade_s:.2f}s "
        f"size={before_size} -> {after_size}"
    )
    assert after == before
    assert after_size < before_size * 0.6  # indexes keep it above half
