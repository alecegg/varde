from dataclasses import replace

from varde_data.views.watch import (
    ActivityFacts,
    WatchFacts,
    WatchTransitionFacts,
    approved_merge_detail,
    approved_merge_elapsed,
    bound_branches,
    frame_events,
    idle_bucket,
    is_waiting_line,
    latest_activity,
    owner_message_after,
    plan_state,
    task_counts,
    waiting_is_live,
    watch_state_detail,
    whole_plan_waiting_on_blocked,
)


def test_latest_activity_preserves_source_precedence_and_equal_timestamp_rules():
    facts = ActivityFacts(
        newest_activity=20,
        activity_source="plan files",
        task_status_times=(30, 30),
        now_line_timestamp=30,
        activity_candidates=((30, "commit"), (31, "uncommitted change")),
    )

    assert latest_activity(facts) == (31, "uncommitted change")
    assert latest_activity(ActivityFacts(20, "plan files", (30,))) == (
        30,
        "task status",
    )
    assert latest_activity(
        ActivityFacts(
            30, "plan files", activity_candidates=((30, "commit"), (30, "build output"))
        )
    ) == (30, "build output")


def test_idle_bucket_tracks_stale_and_merge_ready_windows():
    assert idle_bucket("stale", 120, 60) == 2
    assert idle_bucket("merge-ready", 359, 60) == 1
    assert idle_bucket("merge-ready", 360, 60) == 2
    assert idle_bucket("active", 180, 60) == 0
    assert idle_bucket("stale", 120, 0) == 120


def test_whole_plan_blocked_waits_until_dependencies_finish():
    tasks = [
        {"id": "a", "stem": "a", "status": "blocked", "depends": []},
        {"id": "b", "stem": "b", "status": "todo", "depends": ["a"]},
    ]

    assert whole_plan_waiting_on_blocked(tasks)
    tasks[0]["status"] = "completed"
    assert not whole_plan_waiting_on_blocked(tasks)
    tasks[1]["depends"] = []
    assert not whole_plan_waiting_on_blocked(tasks)
    tasks[0]["status"] = "building"
    assert not whole_plan_waiting_on_blocked(tasks)


def test_plan_state_classification_and_stall_boundary():
    base = WatchFacts(
        now=1200,
        threshold=1200,
        newest_activity=0,
        activity_source="plan files",
        status="active",
        status_bucket="other",
        tasks=({"id": "a", "stem": "a", "status": "todo", "depends": []},),
    )

    assert plan_state(base) == (
        "stale",
        "20m idle; last activity: plan files",
        1200,
    )
    assert plan_state(replace(base, questions=2)) == (
        "needs-decision",
        "2 open question(s)",
        1200,
    )
    assert plan_state(replace(base, done=1)) == (
        "merge-ready",
        "1/1 tasks done",
        1200,
    )
    assert plan_state(replace(base, now_line="waiting: review", waiting_live=True)) == (
        "waiting",
        "",
        1200,
    )
    assert plan_state(replace(base, status_bucket="terminal", plan_age=1200)) == (
        "finished",
        "active",
        1200,
    )
    assert plan_state(replace(base, status_bucket="terminal", plan_age=1201))[0] is None
    assert is_waiting_line("waiting:")
    assert (
        plan_state(replace(base, now_line="waiting:", waiting_live=True))[0]
        == "waiting"
    )


def test_frame_events_orders_transitions_and_preserves_cache_state():
    snapshot = [
        {
            "id": "z",
            "state": "stale",
            "newest_activity": 0,
            "detail": "idle-no-handback; 2m",
            "idle_no_handback": True,
        },
        {
            "id": "a",
            "state": "active",
            "newest_activity": 0,
            "blocked_tasks": ["b", "a"],
        },
    ]
    events, cache = frame_events(snapshot, 120, 60, {}, seed=True)
    assert events == []
    assert cache["z"].idle_no_handback

    events, cache = frame_events(snapshot, 120, 60, {})
    assert [(event.kind, event.plan, event.detail) for event in events] == [
        ("blocked", "a", "a"),
        ("blocked", "a", "b"),
        ("stale", "z", "idle-no-handback; 2m"),
    ]
    events, _ = frame_events(snapshot, 121, 60, cache)
    assert events == []
    assert cache["a"].state == "active"
    assert cache["a"].blocked == frozenset({"a", "b"})


def test_frame_events_suppresses_awaiting_stale_and_blocked_but_emits_other_states():
    plans = [
        {
            "id": state,
            "state": state,
            "detail": "detail",
            "newest_activity": 0,
            "awaiting_user": "approval",
            "blocked_tasks": ["task-a"],
        }
        for state in ("stale", "blocked", "needs-decision", "merge-ready", "finished")
    ]

    events, _ = frame_events(plans, 100, 60, {})

    assert [event.kind for event in events] == [
        "finished",
        "merge-ready",
        "needs-decision",
    ]


def test_waiting_threshold_task_counts_and_branch_binding():
    assert waiting_is_live(179, [0], 60)
    assert not waiting_is_live(180, [0], 60)
    assert not waiting_is_live(100, [], 60)
    assert task_counts(
        [
            {"id": "done", "status": "completed"},
            {"id": "blocked", "status": "blocked"},
            {"id": "open", "status": "todo"},
        ]
    ) == (1, 3, ["blocked"])

    names = [
        "worktree/plan",
        "worktree/plan-task",
        "worktree/plan-child-x",
        "worktree/plan-child",
        "worktree/plan-extra",
        "unrelated",
    ]
    assert bound_branches(
        {"id": "plan", "branch": "worktree/plan-child"},
        [{"id": "task"}],
        {"plan", "plan-child"},
        names,
    ) == ["worktree/plan", "worktree/plan-extra", "worktree/plan-task"]


def test_approved_merge_and_owner_handback_time_rules():
    assert approved_merge_elapsed("1970-01-01T00:00:00Z", 899) is None
    assert approved_merge_elapsed("1970-01-01T00:00:00Z", 900) == 900
    assert approved_merge_elapsed("bad", 900) is None
    assert approved_merge_detail(900, False, False) is None
    assert approved_merge_detail(900, True, True) is None
    assert approved_merge_detail(900, True, False) == "approved 15m ago, not in main"
    assert not owner_message_after(
        [{"from": "plan", "ts": "1970-01-01T00:00:00Z"}], "plan", 0
    )
    assert owner_message_after(
        [{"from": "plan", "ts": "1970-01-01T00:00:01Z"}], "plan", 0
    )
    assert not owner_message_after(
        [{"from": "other", "ts": "1970-01-01T00:00:01Z"}], "plan", 0
    )


def test_watch_state_transition_applies_awaiting_handback_and_stall_rules():
    assert watch_state_detail(
        WatchTransitionFacts("stale", "stale detail", 1200, True, None, False, None)
    ) == ("active", "", False)
    assert watch_state_detail(
        WatchTransitionFacts(
            "stale",
            "stale detail",
            1200,
            True,
            "approved 20m ago, not in main",
            False,
            None,
        )
    ) == ("blocked", "approved 20m ago, not in main", False)
    assert watch_state_detail(
        WatchTransitionFacts("stale", "stale detail", 1200, False, None, True, None)
    ) == ("stale", "stale detail", False)
    assert watch_state_detail(
        WatchTransitionFacts(
            "stale", "stale detail", 1200, False, None, False, "stalled; old slot"
        )
    ) == ("blocked", "stalled; old slot", True)
    assert watch_state_detail(
        WatchTransitionFacts(
            "needs-decision",
            "questions",
            0,
            False,
            "also ignored",
            False,
            "ignored",
        )
    ) == ("needs-decision", "questions", False)
