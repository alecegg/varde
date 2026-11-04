from datetime import UTC, datetime

from varde_data.views.message_receipts import message_receipts


def test_receipt_states_progress_through_read_and_answer() -> None:
    messages = [
        {
            "id": "m-12345678",
            "from": "sender",
            "to": "reader",
            "ts": "2026-10-24T10:00:00Z",
            "text": "hello",
        },
        {
            "id": "m-87654321",
            "from": "reader",
            "to": "sender",
            "ts": "2026-10-24T10:03:00Z",
            "text": "answer",
            "in_reply_to": "m-12345678",
        },
    ]
    deliveries = [
        {
            "message_id": "m-12345678",
            "reader": "reader",
            "event": "pushed",
            "via": "relay",
            "at": "2026-10-24T10:01:00Z",
        },
        {
            "message_id": "m-12345678",
            "reader": "reader",
            "event": "delivered",
            "via": "receipt",
            "at": "2026-10-24T10:02:00Z",
        },
    ]

    receipt = message_receipts(
        messages, deliveries, datetime(2026, 10, 24, 10, 4, tzinfo=UTC)
    )["m-12345678"]

    assert receipt["state"] == "answered"
    assert receipt["timestamps"] == {
        "queued": "2026-10-24T10:00:00Z",
        "pushed": "2026-10-24T10:01:00Z",
        "delivered": "2026-10-24T10:02:00Z",
        "read": "2026-10-24T10:02:00Z",
        "answered": "2026-10-24T10:03:00Z",
    }
    assert receipt["recipients"]["reader"]["undelivered_age_seconds"] is None


def test_pushed_without_claim_remains_undelivered() -> None:
    receipt = message_receipts(
        [
            {
                "id": "m-12345678",
                "from": "sender",
                "to": "reader",
                "ts": "2026-10-24T10:00:00Z",
            }
        ],
        [
            {
                "message_id": "m-12345678",
                "reader": "reader",
                "event": "pushed",
                "via": "relay",
                "at": "2026-10-24T10:01:00Z",
            }
        ],
        datetime(2026, 10, 24, 10, 2, tzinfo=UTC),
    )["m-12345678"]

    assert receipt["state"] == "pushed"
    assert receipt["recipients"]["reader"]["undelivered_age_seconds"] == 120


def test_malformed_message_time_has_no_age_and_is_not_answered() -> None:
    receipt = message_receipts(
        [
            {
                "id": "m-12345678",
                "from": "sender",
                "to": "reader",
                "ts": "garbage",
            },
            {
                "id": "m-87654321",
                "from": "other",
                "to": "sender",
                "ts": "2026-10-24T10:03:00Z",
                "reply_to": "m-12345678",
            },
        ],
        [],
        datetime(2026, 10, 24, 10, 4, tzinfo=UTC),
    )["m-12345678"]

    assert receipt["state"] == "queued"
    assert receipt["timestamps"]["answered"] is None
    assert receipt["recipients"]["reader"]["undelivered_age_seconds"] is None


def test_only_original_recipient_can_answer_a_message() -> None:
    receipt = message_receipts(
        [
            {
                "id": "m-12345678",
                "from": "sender",
                "to": "reader",
                "ts": "2026-10-24T10:00:00Z",
            },
            {
                "id": "m-87654321",
                "from": "other",
                "to": "sender",
                "ts": "2026-10-24T10:03:00Z",
                "reply_to": "m-12345678",
            },
        ],
        [],
        datetime(2026, 10, 24, 10, 4, tzinfo=UTC),
    )["m-12345678"]

    assert receipt["state"] == "queued"
    assert receipt["timestamps"]["answered"] is None
