from datetime import UTC, datetime, timedelta

from varde_workflow.relay_state import load, record


def test_send_liveness_events_are_pruned_by_age_and_cap(tmp_path) -> None:
    now = datetime(2026, 1, 4, tzinfo=UTC)
    record(tmp_path, "send-liveness", now=now - timedelta(days=4), message_id="old")
    for index in range(205):
        record(
            tmp_path,
            "send-liveness",
            now=now - timedelta(minutes=205 - index),
            message_id=str(index),
        )

    events = [
        event for event in load(tmp_path)["events"] if event["event"] == "send-liveness"
    ]
    assert len(events) <= 200
    assert all(
        datetime.fromisoformat(event["at"]) >= now - timedelta(days=3)
        for event in events
    )
