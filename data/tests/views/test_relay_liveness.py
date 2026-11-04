from datetime import UTC, datetime, timedelta

from varde_data.views.relay_liveness import elapsed, mailman_alive

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_mailman_liveness_windows_and_end_state() -> None:
    waiting = ({"event": "waiting", "token_id": "t", "at": NOW.isoformat()},)
    assert mailman_alive("t", NOW + timedelta(seconds=89), waiting)
    assert not mailman_alive("t", NOW + timedelta(seconds=90), waiting)
    returned = ({"event": "returned", "token_id": "t", "at": NOW.isoformat()},)
    assert mailman_alive("t", NOW + timedelta(minutes=4), returned)
    assert not mailman_alive("t", NOW + timedelta(minutes=5), returned)
    ended = (*returned, {"event": "ended", "token_id": "t", "at": NOW.isoformat()})
    assert not mailman_alive("t", NOW, ended)


def test_elapsed_subtracts_sleep_gaps() -> None:
    events = (
        {
            "event": "slept",
            "at": (NOW + timedelta(seconds=10)).isoformat(),
            "gap_seconds": 5,
        },
    )
    assert elapsed(NOW, NOW + timedelta(seconds=30), events) == timedelta(seconds=25)
