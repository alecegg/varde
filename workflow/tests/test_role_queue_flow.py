from varde_data.records.queue import QueueItem
from varde_workflow.role_queue_flow import follow_up


def test_builder_completion_enqueues_nothing():
    done = QueueItem(
        "task-build",
        "plan",
        owned_files="src/a.py",
        role="builder",
        queue_name="roles/plan",
    )

    assert follow_up(done, "done") == ()


def test_reviewer_findings_enqueue_builder_fix():
    done = QueueItem(
        "task-build-review", "plan", owned_files="src/a.py", role="reviewer"
    )

    follow_up_item = follow_up(done, "findings")

    assert len(follow_up_item) == 1
    fix = follow_up_item[0]
    assert fix.id == "task-build-review-fix"
    assert fix.role == "builder"
    assert fix.extra is not None
    assert fix.extra["kind"] == "fix"
    assert fix.owned_files == "src/a.py"


def test_reviewer_pass_and_unhandled_roles_have_no_follow_up():
    reviewer = QueueItem("review", "plan", role="varde-reviewer")
    planner = QueueItem("plan", "plan", role="planner")

    assert follow_up(reviewer, "pass") == ()
    assert follow_up(planner, "done") == ()
