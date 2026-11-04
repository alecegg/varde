from varde_runner.role_queue import (
    RoleQueueRow,
    RoleSummary,
    home_sort,
    needs_you_count_text,
    role_status_line,
)


def summary(role, state, *, current=None, queued=0, needs_you=0):
    return RoleSummary(role, None, state, current, queued, needs_you)


def test_role_status_line_formats_all_states_and_truncates_titles():
    long_title = "x" * 50
    assert (
        role_status_line(
            summary(
                "builder",
                "running",
                current=RoleQueueRow("1", long_title, None, "running"),
                queued=3,
            )
        )
        == f"Working on {'x' * 40}, 3 in queue"
    )
    assert role_status_line(summary("reviewer", "needs_you", needs_you=2)) == (
        "Needs you: 2 approvals"
    )
    assert role_status_line(summary("planner", "idle")) == "Idle"
    assert role_status_line(summary("planner", "idle", queued=4)) == "Idle, 4 in queue"
    assert role_status_line(summary("planner", "done")) == "Done"


def test_needs_you_label_caps_a_large_count():
    assert needs_you_count_text(0) == "0"
    assert needs_you_count_text(2) == "2"
    assert needs_you_count_text(9) == "9"
    assert needs_you_count_text(12) == "9+"
    assert role_status_line(summary("reviewer", "needs_you", needs_you=12)) == (
        "Needs you: 9+ approvals"
    )


def test_home_sort_groups_by_priority_and_preserves_order_within_groups():
    rows = [
        summary("first done", "done"),
        summary("first idle", "idle"),
        summary("first running", "running"),
        summary("first needs", "needs_you"),
        summary("second running", "running"),
        summary("second needs", "needs_you"),
    ]

    assert [item.role for item in home_sort(rows)] == [
        "first needs",
        "second needs",
        "first running",
        "second running",
        "first idle",
        "first done",
    ]
