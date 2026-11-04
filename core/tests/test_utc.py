from datetime import UTC, datetime, timedelta, timezone

import pytest
from varde_core.utc import as_utc, in_window, parse_datetime, utc_day, window_start


def test_as_utc_attaches_or_converts_timezone() -> None:
    assert as_utc(datetime(2026, 1, 2, 3)) == datetime(2026, 1, 2, 3, tzinfo=UTC)
    offset = timezone(timedelta(hours=2))
    assert as_utc(datetime(2026, 1, 2, 3, tzinfo=offset)) == datetime(
        2026, 1, 2, 1, tzinfo=UTC
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-01-02T03:04:05", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)),
        (
            "2026-01-02T03:04:05+02:00",
            datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=2))),
        ),
        ("bad", None),
        (None, None),
        (42, None),
    ],
)
def test_parse_datetime(value: object, expected: datetime | None) -> None:
    assert parse_datetime(value) == expected


def test_utc_day_and_window_helpers() -> None:
    value = datetime(2026, 1, 2, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    assert utc_day(value).isoformat() == "2026-01-01"
    assert window_start(value, days=1, hours=2) == datetime(
        2025, 12, 31, 20, 30, tzinfo=UTC
    )
    assert in_window(value, window_start(value, hours=1), as_utc(value))
    assert not in_window(
        value, window_start(value, hours=1), window_start(value, hours=2)
    )
