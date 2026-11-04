from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest
from varde_data.config import DataConfig
from varde_data.open import open_data
from varde_data.records.messages import NewMessage
from varde_runner.cache import SingleFlightCache
from varde_runner.web.cache import InboxStoreCache


def test_inbox_cache_tracks_repository_version(tmp_path: Path) -> None:
    repository = open_data(tmp_path, DataConfig()).messages
    cache = InboxStoreCache(tmp_path)

    assert cache.read().messages == []
    repository.append(NewMessage("main", "runner", "info", "new message"))

    assert [row["text"] for row in cache.read().messages] == ["new message"]


def test_singleflight_cache_tracks_foreground_and_background_failures() -> None:
    cache = SingleFlightCache()

    def fail_load() -> None:
        raise RuntimeError("failed")

    with pytest.raises(RuntimeError, match="failed"):
        cache.get("source", 30, fail_load, negative_ttl=0)
    assert cache.failing("source")
    cache.clear()
    assert not cache.failing("source")

    assert cache.get("source", 30, lambda: "recovered") == "recovered"
    assert not cache.failing("source")

    finished = Event()

    def fail_refresh() -> None:
        finished.set()
        raise RuntimeError("refresh failed")

    assert cache.get_swr("source", 0, fail_refresh) == "recovered"
    assert finished.wait(timeout=2)
    # The loader signals before raising; wait for the refresh worker to record it.
    for _ in range(100):
        if cache.failing("source"):
            break
        Event().wait(0.01)
    assert cache.failing("source")
    cache.invalidate("source", refresh=False)
    assert not cache.failing("source")
