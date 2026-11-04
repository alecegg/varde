from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from varde_data.backends.sqlite.queue_schema import SCHEMA_VERSION
from varde_data.config import DataConfig, load_data_config
from varde_data.errors import Invalid, WrongMode
from varde_data.open import open_data
from varde_data.queue import open_queue
from varde_data.queue_mode_lock import operation
from varde_data.queue_paths import (
    QUEUE_DATABASE,
    queue_database_for,
    queue_migration_pending,
)
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItemInput


def test_queue_domain_and_backends_load_lazily(tmp_path: Path) -> None:
    sys.modules.pop("varde_data.queue", None)
    sys.modules.pop("varde_data.backends.memory.queue", None)
    sys.modules.pop("varde_data.backends.sqlite.queue", None)
    data = open_data(tmp_path, DataConfig(backends={"queue": "memory"}))
    assert "varde_data.queue" not in sys.modules
    repository = data.queue
    assert repository is data.queue
    assert "varde_data.backends.memory.queue" in sys.modules
    assert "varde_data.backends.sqlite.queue" not in sys.modules


def test_queue_backend_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VARDE_DATA_QUEUE_BACKEND", "memory")
    config = load_data_config(tmp_path)
    assert config.backends["queue"] == "memory"
    assert open_data(tmp_path, config).queue is not None


def test_memory_queue_is_independent_of_sqlite_store_mode(tmp_path: Path) -> None:
    repository = open_queue(tmp_path, "memory")
    stored = repository.enqueue(QueueItemInput("one", "plan"))

    assert repository.get(stored.queue_name, "one") == stored
    assert not (tmp_path / ".cache" / "data" / "queue.sqlite3").exists()


def test_queue_refuses_newer_domain_version(tmp_path: Path) -> None:
    version = tmp_path / ".cache" / "data" / "queue.version"
    version.parent.mkdir(parents=True)
    version.write_text(f"{SCHEMA_VERSION + 1}\n", encoding="ascii")
    with pytest.raises(Invalid, match=f"newer than supported version {SCHEMA_VERSION}"):
        _ = open_data(tmp_path, DataConfig()).queue
    assert version.read_text(encoding="ascii") == f"{SCHEMA_VERSION + 1}\n"


def test_malformed_queue_marker_fails_closed(tmp_path: Path) -> None:
    marker = tmp_path / ".cache/data/queue.version"
    marker.parent.mkdir(parents=True)
    marker.write_text("three\n", encoding="ascii")

    with pytest.raises(Invalid, match="invalid queue version marker"):
        queue_database_for(tmp_path)


def test_empty_queue_does_not_report_a_pending_migration(tmp_path: Path) -> None:
    assert queue_migration_pending(tmp_path) is False


def test_queue_repository_calls_require_sqlite_mode(tmp_path: Path) -> None:
    initialize(tmp_path)
    repository = open_data(tmp_path, DataConfig()).queue
    with operation(tmp_path) as mode:
        assert mode == "markdown"
        with pytest.raises(WrongMode):
            repository.list()

    database = tmp_path / QUEUE_DATABASE
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'"
        )
    with operation(tmp_path) as mode:
        assert mode == "sqlite"
        stored = repository.enqueue(QueueItemInput("one", "plan"))
    assert stored.id == "one"


def test_slots_domain_loads_lazily_and_uses_sqlite(tmp_path: Path) -> None:
    sys.modules.pop("varde_data.queue", None)
    initialize(tmp_path)
    with sqlite3.connect(tmp_path / QUEUE_DATABASE) as connection:
        connection.execute(
            "UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'"
        )
    data = open_data(tmp_path, DataConfig())
    assert "varde_data.queue" not in sys.modules
    repository = data.slots
    assert repository is data.slots
    assert "varde_data.backends.sqlite.slots" in sys.modules


def test_slot_repository_calls_require_sqlite_mode(tmp_path: Path) -> None:
    initialize(tmp_path)
    database = tmp_path / QUEUE_DATABASE
    with pytest.raises(WrongMode):
        _ = open_data(tmp_path, DataConfig()).slots
    assert database.exists()
