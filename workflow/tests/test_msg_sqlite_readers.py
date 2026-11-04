from pathlib import Path

import pytest
from varde_data.messages import open_messages
from varde_data.records.messages import NewMessage
from varde_data.store_mode import _mark_import_verified, set_store_mode


@pytest.mark.parametrize(
    "mode", ["files", "memory", "sqlite", "mirror-files", "mirror-sqlite"]
)
def test_status_events_are_read_through_message_repository(
    tmp_path: Path, mode: str
) -> None:
    _mark_import_verified(tmp_path, verified_at="2026-10-24T00:00:00Z")
    if mode in {"sqlite", "mirror-files", "mirror-sqlite"}:
        set_store_mode(tmp_path, "mirror-files")
    if mode in {"sqlite", "mirror-sqlite"}:
        set_store_mode(tmp_path, "mirror-sqlite")
    if mode == "sqlite":
        set_store_mode(tmp_path, "sqlite")
    repository = open_messages(tmp_path, mode)
    repository.append(NewMessage("worker", "sender", "info", "mail"))
    inbox = tmp_path / ".cache" / "inbox"
    (inbox / "events.jsonl").write_text('{"event":"refuse"}\n', encoding="utf-8")

    expected = [] if mode == "memory" else ["refuse"]
    assert [row["event"] for row in repository.status_events()] == expected
