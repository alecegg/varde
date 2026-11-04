from varde_learn.loop.review.spend_roles import attribute, plan, role


def test_role_heuristics_cover_workflow_roles():
    assert role("You are the plan orchestrator for this task", False) == "orchestrator"
    assert role("Review the branch and report findings", False) == "reviewer/checker"
    assert role("Follow varde-planner and plan the change", False) == "planner"
    assert role("Run a varde-learn friction cycle", False) == "learn"
    assert role("Implement this bounded task as the builder", False) == "builder"
    assert role("Probe wake-drill output", False) == "probe"
    assert role("Anything else", True) == "in-session subagent"
    assert role("Hello", False) == "main/interactive/other"


def test_role_uses_report_tables_precedence_and_empty_prompt():
    assert role("", False) == "main/interactive/other"
    assert role("review builder orchestrator", False) == "orchestrator"
    assert role("review builder", False) == "reviewer/checker"
    assert role("implement this", False) == "main/interactive/other"
    assert role("plan something", False) == "main/interactive/other"


def test_plan_extracts_identifier_from_plan_path_or_id_phrase():
    assert plan("Task from plans/2026-10-23-learn-review-token-spend/tasks/a.md") == (
        "2026-10-23-learn-review-token-spend"
    )
    assert plan("plan id `daily-review`") == "daily-review"
    assert plan("No plan mentioned") is None


def test_attribute_inherits_parent_plan_and_counts_unclassified_sessions():
    result = attribute(
        [
            {
                "session_id": "parent",
                "first_prompt": "Builder task for plan id `spend-classification`",
            },
            {
                "session_id": "parent",
                "is_subagent": True,
                "first_prompt": "Inspect tests",
            },
            {"session_id": "unknown", "first_prompt": "Hello"},
        ]
    )
    parent, child, unknown = result["sessions"]
    assert (parent["role"], parent["plan"]) == ("builder", "spend-classification")
    assert (child["role"], child["plan"], child["parent_role"]) == (
        "in-session subagent",
        "spend-classification",
        "builder",
    )
    assert unknown["plan"] is None
    assert result["unclassified"] == 1


def test_attribute_counts_unclassified_children_and_exposes_rows_for_spend():
    rows = [
        {"session_id": "unknown", "first_prompt": "Hello", "calls": 2, "weighted": 9},
        {
            "session_id": "unknown",
            "is_subagent": True,
            "first_prompt": "Child prompt",
            "calls": 3,
            "weighted": 12,
        },
    ]
    result = attribute(rows)
    assert result["unclassified"] == 2
    assert result["unclassified_rows"] == result["sessions"]
    assert sum(row["calls"] for row in result["unclassified_rows"]) == 5
    assert sum(row["weighted"] for row in result["unclassified_rows"]) == 21
    assert result["sessions"][1]["parent_role"] == "main/interactive/other"


def test_attribute_missing_and_empty_parent_ids_do_not_match_unrelated_rows():
    result = attribute(
        [
            {"first_prompt": "Review this"},
            {"is_subagent": True, "first_prompt": "plan id `child-plan`"},
            {
                "session_id": "parent",
                "first_prompt": "Review parent",
            },
            {
                "session_id": "child",
                "parent_session_id": "absent",
                "is_subagent": True,
                "first_prompt": "plan id `own-plan`",
            },
        ]
    )
    no_id_child, absent_parent_child = result["sessions"][1], result["sessions"][3]
    assert no_id_child["parent_role"] is None
    assert no_id_child["plan"] == "child-plan"
    assert absent_parent_child["parent_role"] is None
    assert absent_parent_child["plan"] == "own-plan"


def test_attribute_supports_short_fields_and_does_not_mutate_inputs():
    parent = {"sid": "p", "first": "Review plan id `short-plan`"}
    child = {"sid": "p", "sub": True, "first": "Child"}
    result = attribute([parent, child])
    assert result["sessions"][1]["plan"] == "short-plan"
    assert result["sessions"][1]["parent_role"] == "reviewer/checker"
    assert "role" not in parent
    assert "plan" not in child
