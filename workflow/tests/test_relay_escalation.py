from __future__ import annotations

from datetime import UTC, datetime, timedelta

from varde_workflow.binding import BindingStore
from varde_workflow.commands.msg import append_message, read_all
from varde_workflow.relay_state import escalate_due


def test_banner_side_escalation_is_idempotent(tmp_path) -> None:
    now = datetime(2026, 10, 17, 12, tzinfo=UTC)
    store = BindingStore(tmp_path)
    marker = store.issue("main", supersede=True, now=now)
    assert store.redeem(marker, "main-session", "claude", str(tmp_path), now=now)
    append_message(
        "sender",
        "orphan",
        "blocked",
        "urgent",
        working=tmp_path,
        now=now - timedelta(minutes=11),
    )

    assert len(escalate_due(tmp_path, now)) == 1
    assert escalate_due(tmp_path, now) == []
    assert (
        sum(
            message.from_ == "relay" and message.to == "main"
            for message in read_all(tmp_path)
        )
        == 1
    )
