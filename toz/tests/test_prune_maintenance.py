from __future__ import annotations

from dataclasses import dataclass

from varde_toz.chunk import chunk_default
from varde_toz.store import NewCapture, Store


@dataclass
class Retention:
    days: int
    superseded_days: int
    max_mb: int


def test_prune_deletes_expired_and_preserves_search(tmp_path):
    store = Store.open(tmp_path / "toz.db")

    def add(label, body):
        return store.insert_capture(
            NewCapture(label, "run", label, bytes=len(body)),
            [("stdout", c) for c in chunk_default(body)],
        )

    add("expired", "expiredonly marker for old capture\n")
    store.conn.execute("UPDATE captures SET created_at=0 WHERE label='expired'")
    survivor = add("survivor", "quartzneedle retained searchable content\n")
    assert store.search("quartzneedle")
    assert store.prune(Retention(0, 0, 500)) == 1
    assert store.get_by_handle(survivor)["label"] == "survivor"
    assert store.search("quartzneedle")
    store.close()
