from __future__ import annotations

from varde_toz.chunk import chunk_default
from varde_toz.store import NewCapture, Store


def test_capture_write_budget_stays_bounded(tmp_path):
    path = tmp_path / "toz.db"
    body = "capture record has useful searchable words and trace data\n" * 1024
    with Store(path) as store:
        store.insert_capture(
            NewCapture("budget", "capture", "budget", bytes=len(body)),
            [("stdout", chunk) for chunk in chunk_default(body)],
        )
        size = store.db_size_bytes()
    assert size < 8 * len(body)
