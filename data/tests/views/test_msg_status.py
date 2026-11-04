from datetime import UTC, datetime

from varde_data.views.msg_status import banner, build_report


def test_status_view_computes_unbound_pending_and_alert_banner() -> None:
    now = datetime(2026, 10, 17, 12, tzinfo=UTC)
    report = build_report(
        [{"id": "m1", "to": "guest", "kind": "info", "ts": "2026-10-17T11:00:00Z"}],
        [],
        [],
        [],
        now,
        is_urgent=lambda _message, _bindings: False,
    )
    assert report["unbound_pending"] == ["guest"]
    text = banner(report)
    assert text is not None
    assert text.startswith("varde msg status: pending mail for unbound addresses")


def test_status_view_exposes_oldest_undelivered_age() -> None:
    now = datetime(2026, 10, 17, 12, tzinfo=UTC)
    report = build_report(
        [{"id": "m1", "to": "worker", "kind": "info", "ts": "2026-10-17T11:55:00Z"}],
        [],
        [],
        [],
        now,
    )
    worker = report["addresses"][0]
    assert worker["oldest_undelivered_age_seconds"] == 300
