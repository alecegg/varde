from varde_learn.loop.sweep.core import (
    dedupe_against_open,
    findings_from_metrics,
    select_unanalyzed,
)


def test_select_unanalyzed_omits_ledger_and_includes_workers():
    sessions = [
        {
            "harness": "codex",
            "session_id": "root",
            "workers": [{"harness": "claude", "session_id": "worker"}],
        },
        {"harness": "opencode", "session_id": "old", "workers": []},
    ]
    ledger = [{"harness": "opencode", "session": "old"}]

    assert [row["session_id"] for row in select_unanalyzed(sessions, ledger)] == [
        "root",
        "worker",
    ]


def test_finding_key_is_command_level_and_open_dedupe_only():
    one = findings_from_metrics({"command_failures": {"pytest": {"failures": 3}}}, "a")
    two = findings_from_metrics({"command_failures": {"pytest": {"failures": 3}}}, "b")
    assert one[0]["dedupe_key"] == two[0]["dedupe_key"]
    assert dedupe_against_open(one, []) == one
    assert (
        dedupe_against_open(
            one, [{"status": "resolved", "dedupe_key": one[0]["dedupe_key"]}]
        )
        == one
    )
    assert (
        dedupe_against_open(
            one, [{"status": "open", "dedupe_key": one[0]["dedupe_key"]}]
        )
        == []
    )


def test_command_finding_key_ignores_call_counts():
    one = findings_from_metrics(
        {"command_failures": {"pytest": {"failures": 1, "calls": 3}}}, "one"
    )[0]
    two = findings_from_metrics(
        {"command_failures": {"pytest": {"failures": 7, "calls": 12}}}, "two"
    )[0]
    assert one["dedupe_key"] == two["dedupe_key"]
    assert one["evidence"]["failures"] == 1
    assert two["evidence"]["failures"] == 7
