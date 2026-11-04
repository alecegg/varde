from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "friction"
GOLDENS = FIXTURES / "old-learn"
REPO_ROOT = Path(__file__).resolve().parents[2]

_DATA_SCRIPT = r"""
import base64
import json
import os
import sqlite3
import sys
from pathlib import Path

from varde_data.backends.files.friction import FilesFriction
from varde_data.backends.sqlite.friction import SqliteFrictionIndex
from varde_data.friction_events import fold, replay
from varde_data.repos.friction import FrictionAddRequest, FrictionImportEntry

scenario, root_arg = sys.argv[1:]
root = Path(root_arg)


def dump(directory):
    with sqlite3.connect(directory / "learn.db") as db:
        tables = (
            "items", "occurrences", "status_changes", "adoptions",
            "adoption_items", "item_tags", "incident_provenance",
        )
        result = {}
        for table in tables:
            rows = db.execute(f'SELECT * FROM "{table}"').fetchall()
            result[table] = sorted(rows, key=lambda row: json.dumps(row, default=str))
        row = db.execute("SELECT value FROM meta WHERE key='log_map'").fetchone()
        result["id_map"] = json.loads(row[0]) if row else None
    result["log_bytes"] = base64.b64encode(
        (directory / "friction.jsonl").read_bytes()
    ).decode()
    return result


import varde_data.friction_events as data_log

os.getpid = lambda: 77
data_log._counter = 0
SqliteFrictionIndex(root).refresh()

if scenario == "redaction":
    from varde_data.records.friction import Event, ItemAdded, OccurrenceAppended

    title = "Build AKIA1234567890ABCDEF"
    evidence = "token AKIA1234567890ABCDEF was exposed"
    item = Event.at(
        "2026-01-01T00:00:00.000Z",
        None,
        ItemAdded(title, "test"),
        pid=77,
        counter=0,
    )
    occurrence = Event.at(
        "2026-01-01T00:00:00.001Z",
        None,
        OccurrenceAppended(
            item.id, "2026-01-01T00:00:00.000Z", "/tmp", evidence
        ),
        pid=77,
        counter=1,
    )
    FilesFriction(root).append_events([item, occurrence])
    SqliteFrictionIndex(root).refresh()

if scenario == "slug-collision":
    from varde_data.records.friction import Event, ItemAdded

    event = Event.at(
        "2026-02-01T00:00:00.000Z",
        None,
        ItemAdded("fixture", "test"),
        pid=77,
        counter=0,
    )
    FilesFriction(root).append_event(event)
    SqliteFrictionIndex(root).refresh()
    store = FilesFriction(root)
    items = {item.title: item for item in store.list_items().items}
    assert items["Fixture item"].slug == "fixture"
    assert items["fixture"].slug == "fixture-2"
    assert store.show("fixture").item.title == "Fixture item"

if scenario == "import-mappings":
    data_log._counter = 0
    entries = (
        FrictionImportEntry(
            slug="custom-one",
            title="Legacy One",
            source="test",
            created_at="2026-03-01T00:00:00.000Z",
            id=17,
        ),
        FrictionImportEntry(
            slug="custom-two",
            title="Legacy Two",
            source="test",
            created_at="2026-03-02T00:00:00.000Z",
            id=31,
        ),
    )
    store = FilesFriction(root)
    store.import_entries(entries)
    before = (root / "friction.jsonl").read_bytes()
    (root / "learn.db").unlink()
    store = FilesFriction(root)
    items = {item.title: item for item in store.list_items().items}
    assert {title: item.slug for title, item in items.items()} == {
        "Fixture item": "fixture-item",
        "Legacy One": "legacy-one",
        "Legacy Two": "legacy-two",
    }
    assert (root / "friction.jsonl").read_bytes() == before

data_dump = dump(root)
if scenario == "import-mappings":
    data_dump.pop("id_map")
    data_dump.pop("log_bytes")
if scenario == "redaction":
    events = replay(root).events
    assert sum(event.redacted for event in events) == 2
    assert "AKIA1234567890ABCDEF" not in repr([event.to_dict() for event in events])
if scenario == "add-before-read":
    store = FilesFriction(root)
    store.add(FrictionAddRequest("Fresh item", "test", "new evidence", "/tmp"))
    titles = {item.title for item in fold(replay(root).events).items}
    assert titles == {"Fixture item", "Fresh item"}
    assert (root / "learn.db.pre-log").is_file()
print(json.dumps(data_dump, sort_keys=True))
"""


def _scenarios() -> list[tuple[str, Path, bool]]:
    scenarios = []
    for version in range(1, 6):
        source = FIXTURES / f"schema-v{version}"
        scenarios.extend(
            (
                (f"v{version}-no-log", source, False),
                (f"v{version}-with-log", source, True),
            )
        )
    scenarios.extend(
        (
            ("legacy-no-log", FIXTURES / "legacy-no-log", False),
            ("empty-log", FIXTURES / "empty-log", False),
            ("torn-only-log", FIXTURES / "torn-only-log", False),
            ("interrupted-migration", FIXTURES / "interrupted-migration", False),
            ("add-before-read", FIXTURES / "add-before-read", False),
            ("redaction", FIXTURES / "empty-log", False),
            ("slug-collision", FIXTURES / "schema-v5", False),
            ("import-mappings", FIXTURES / "empty-log", False),
        )
    )
    return scenarios


@pytest.mark.parametrize(
    ("scenario", "source", "with_shared_log"),
    _scenarios(),
    ids=lambda value: value,
)
def test_data_migration_matches_old_learn_golden(
    tmp_path: Path, scenario: str, source: Path, with_shared_log: bool
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    if source.name == "interrupted-migration":
        shutil.copytree(source, data_root, dirs_exist_ok=True)
    else:
        shutil.copy2(source / "learn.db", data_root / "learn.db")
        if with_shared_log:
            shutil.copy2(FIXTURES / "friction.jsonl", data_root / "friction.jsonl")
        elif (source / "friction.jsonl").exists():
            shutil.copy2(source / "friction.jsonl", data_root / "friction.jsonl")

    result = subprocess.run(  # noqa: S603 - fixed script and temporary test paths
        [sys.executable, "-c", _DATA_SCRIPT, scenario, str(data_root)],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    actual = json.loads(result.stdout)
    expected = json.loads((GOLDENS / f"{scenario}.json").read_text())
    assert actual == expected
