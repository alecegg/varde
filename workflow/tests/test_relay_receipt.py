from datetime import UTC, datetime

from varde_workflow.relay_state import action_record, lease_actions


def test_action_record_reads_leased_receipt_record(tmp_path):
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    action = lease_actions(
        tmp_path,
        [{"to": "worker", "message_ids": ["m-01234567"]}],
        "mailman-token",
        now,
    )[0]

    assert action_record(tmp_path, action["action_id"]) == action
    assert action_record(tmp_path, "missing") is None
