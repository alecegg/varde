from pathlib import Path

from varde_data.records.friction import Event, ItemAdded
from varde_learn.loop.friction_repository import open_repository
from varde_learn.loop.store import read
from varde_learn.loop.store.types import FrictionListRequest, PageRequest


def test_listing_many_items_reads_event_log_once(tmp_path: Path) -> None:
    repository = open_repository(tmp_path)
    repository.import_events(
        [
            Event.at(
                f"2026-01-01T00:{index // 60:02}:{index % 60:02}.000Z",
                None,
                ItemAdded(f"Item {index}", "test"),
                pid=1,
                counter=index,
            )
            for index in range(600)
        ]
    )
    event_log = repository.event_log
    calls = 0

    def counted_event_log():
        nonlocal calls
        calls += 1
        return event_log()

    repository.event_log = counted_event_log  # type: ignore[method-assign]

    page = read.list_items(
        repository,
        FrictionListRequest(
            status=None,
            source=None,
            repo_root=None,
            global_=False,
            text=None,
            cwd=tmp_path,
            page=PageRequest(offset=0, limit=500),
        ),
    )

    assert page.total == 600
    assert len(page.items) == 500
    assert calls == 1
