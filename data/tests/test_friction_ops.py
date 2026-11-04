from varde_data.errors import Invalid
from varde_data.friction_events import fold
from varde_data.friction_ops import filter_items, list_recurrences, plan_import_entries
from varde_data.records.friction import (
    Event,
    ItemAdded,
    LogAdoption,
    LogItem,
    LogOccurrence,
    LogState,
)
from varde_data.repos.friction import FrictionImportEntry


def test_filter_validation_and_repo_global_filters():
    item = Event.at(
        "2026-01-01T00:00:00.000Z", None, ItemAdded("Global", "s"), pid=1, counter=1
    )
    state = fold([item])
    assert filter_items(state, global_=True).total == 1
    assert filter_items(state, repo_root="/repo").total == 0
    try:
        filter_items(state, global_=True, repo_root="/repo")
    except Invalid:
        pass
    else:
        raise AssertionError("conflicting scope filters must be invalid")


def test_empty_recurrence_page():
    assert list_recurrences(fold([])).page.total == 0


def test_recurrences_compare_instants_and_skip_invalid_timestamps():
    item = LogItem("item", "alpha", "Alpha", "test", None, None, "open", "", [])
    state = LogState(
        items=[item],
        occurrences=[
            LogOccurrence(
                "equal",
                "item",
                "2025-01-02T00:00:00Z",
                "/work",
                None,
                None,
                "equal",
                None,
                None,
            ),
            LogOccurrence(
                "later",
                "item",
                "2025-01-02T00:00:01Z",
                "/work",
                None,
                None,
                "later",
                None,
                None,
            ),
            LogOccurrence(
                "invalid",
                "item",
                "not-a-date",
                "/work",
                None,
                None,
                "invalid",
                None,
                None,
            ),
        ],
        status_changes=[],
        adoptions=[
            LogAdoption(
                "adoption",
                "2025-01-01T19:00:00-05:00",
                "adopted",
                [],
                None,
                None,
                None,
                ["item"],
            ),
            LogAdoption(
                "invalid-adoption", "not-a-date", "bad", [], None, None, None, ["item"]
            ),
        ],
        orphaned_events=0,
    )

    report = list_recurrences(state)

    assert [row.occurrence.event_id for row in report.page.items] == ["later"]
    assert report.skipped_invalid_timestamps == 2


def test_import_plan_deduplicates_by_stored_slug():
    state = fold(
        [
            Event.at(
                "2026-01-01T00:00:00.000Z",
                None,
                ItemAdded("Different title", "s"),
                pid=1,
                counter=1,
            )
        ]
    )
    entry = FrictionImportEntry("stored-slug", "Different title", "s")
    accepted, skipped = plan_import_entries(state, (entry,), imported_slugs={})
    assert accepted == (entry,) and skipped == 0
    accepted, skipped = plan_import_entries(state, (entry, entry), imported_slugs={})
    assert accepted == (entry,) and skipped == 1
