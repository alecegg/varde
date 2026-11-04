"""One domain on sqlite leaves the other domains and every ``--json`` output alone."""

from __future__ import annotations

import io
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_data.calls import open_calls
from varde_data.friction import open_friction
from varde_data.learn_store_mode import DOMAINS, read_learn_mode
from varde_data.ledger import open_ledger
from varde_learn.loop.cli_calls import run as run_calls
from varde_learn.loop.cli_friction_read import run_list
from varde_learn.module import register

GOLDEN = Path(__file__).parent / "golden" / "friction"
SOURCES = {
    "friction": ("friction.jsonl",),
    "ledger": ("analyzed.jsonl", "digests/2026-01-01.json"),
    "calls": ("cli_calls.jsonl",),
}
TABLES = {
    "friction": "friction_events",
    "ledger": "analyzed",
    "calls": "cli_calls",
}


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store = tmp_path / "learn"
    store.mkdir()
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    shutil.copyfile(GOLDEN / "friction.jsonl", store / "friction.jsonl")
    open_friction(store, "files").list_items()  # builds the legacy learn.db index
    ledger = open_ledger(store, "files")
    ledger.mark("codex", "s1", "2026-01-01T00:00:00Z", "first")
    ledger.mark("claude", "s2", "2026-01-02T00:00:00Z", "second")
    from datetime import date

    ledger.write_digest(date(2026, 1, 1), "digest", [{"slug": "a"}])
    calls = open_calls(store, "files")
    for index, status in enumerate(("success", "failure", "success")):
        calls.append(
            {
                "ts": f"2026-01-0{index + 1}T00:00:00Z",
                "command": "plan status",
                "status": status,
                "duration_s": 0.1,
                "session": "sess",
            }
        )
    return store


def _json_outputs() -> dict[str, object]:
    friction = SimpleNamespace(stdout=io.StringIO(), stderr=io.StringIO())
    assert run_list({"json": True, "limit": 1000}, friction) == 0
    calls = SimpleNamespace(stdout=io.StringIO(), stderr=io.StringIO())
    assert run_calls(["calls", "--json"], calls) == 0
    return {
        "friction list": json.loads(friction.stdout.getvalue()),
        "calls": json.loads(calls.stdout.getvalue()),
    }


def _ledger_view(root: Path) -> tuple[object, object]:
    ledger = open_ledger(root)
    from datetime import date

    return ledger.analyzed(), ledger.read_digest(date(2026, 1, 1))


def _bytes(root: Path) -> dict[str, bytes]:
    return {
        name: (root / name).read_bytes() for names in SOURCES.values() for name in names
    }


def _rows(root: Path, table: str) -> int:
    path = root / "learn.sqlite3"
    if not path.is_file():
        return 0
    with closing(sqlite3.connect(path)) as db:
        return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608


@pytest.mark.parametrize("domain", DOMAINS)
def test_one_domain_on_sqlite_leaves_the_others_on_files(
    root: Path, capsys: pytest.CaptureFixture[str], domain: str
) -> None:
    outputs = _json_outputs()
    ledger_view = _ledger_view(root)
    sources = _bytes(root)

    code = register().run(["learn", "store", "migrate", "--domain", domain, "--json"])
    assert code == 0, capsys.readouterr()
    capsys.readouterr()

    record = read_learn_mode(root)
    assert {name: record.mode(name) for name in DOMAINS} == {
        name: "sqlite" if name == domain else "files" for name in DOMAINS
    }
    after = _json_outputs()
    if domain == "calls":  # only the sqlite calls store prunes, so it adds the notice
        meta = after["calls"]["meta"]  # type: ignore[index]
        assert meta.pop("retention_days") == 30
    assert after == outputs
    assert _ledger_view(root) == ledger_view
    assert _bytes(root) == sources
    for other in DOMAINS:
        if other != domain:
            assert _rows(root, TABLES[other]) == 0
    assert _rows(root, TABLES[domain]) > 0
