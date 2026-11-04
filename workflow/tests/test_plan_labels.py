from varde_workflow.plan_labels import (
    label_findings,
    resolve_group,
    resolve_parent_group,
    suggest_label,
)


def test_resolve_group_prefers_nonempty_own_value() -> None:
    assert resolve_group(" Child group ", "Parent") == "Child group"


def test_resolve_group_inherits_parent_for_missing_or_blank_value() -> None:
    assert resolve_group(None, "Parent") == "Parent"
    assert resolve_group("  ", "Parent") == "Parent"


def test_resolve_parent_group_uses_nearest_nonempty_ancestor() -> None:
    assert resolve_parent_group([None, "  ", "Grandparent"]) == "Grandparent"


def test_label_findings_reports_missing_fields() -> None:
    assert label_findings(None, "") == ["missing label", "missing group"]


def test_label_findings_enforces_length_and_format_rules() -> None:
    assert label_findings("One Two", "Group") == ["label must be 3 to 5 words"]
    assert label_findings("One Two Three Four Five Six", "Group") == [
        "label must be 3 to 5 words"
    ]
    findings = label_findings(
        "Fix issue 20261022 v2 abc-plan", "Group", "Fix issue", "abc-plan"
    )
    assert len(findings) == 3
    assert all("label must" in finding for finding in findings)


def test_label_findings_rejects_iso_date() -> None:
    assert label_findings("Fix 2026-10-22 imports", "Group") == [
        "label must not contain an ISO date"
    ]


def test_label_findings_accepts_valid_label_and_detects_duplicate() -> None:
    assert label_findings("A Good Label", "Group") == []
    assert label_findings(
        "A Good Label", "Group", other_open_labels={"a good label"}
    ) == ["label must be unique among open plans"]


def test_suggest_label_removes_leading_filler_and_caps_length() -> None:
    assert (
        suggest_label("Make sure to Fix Mobile Plans scrolling")
        == "Make sure to Fix Mobile"
    )
    assert (
        suggest_label("The Quality Score Optimization Workstream")
        == "Quality Score Optimization"
    )
    assert len(suggest_label("Retune " + "ExtremelyLongWord" * 3)) <= 36


def test_suggest_label_keeps_outcome_verbs_and_omits_short_suggestion() -> None:
    assert suggest_label("Add missing language pairs") == "Add missing language pairs"
    assert label_findings("Weak Label", "Group", "Fix it") == [
        "label must be 3 to 5 words"
    ]
