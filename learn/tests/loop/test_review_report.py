from datetime import date

from varde_learn.loop.review.report import (
    friction_candidates,
    friction_evidence,
    render_report,
    review_friction_key,
    write_report,
)

SECRET = "0123456789abcdef" * 4


def test_report_has_setup_project_sections_and_evidence(tmp_path):
    findings = {
        "setup": [
            {
                "title": "Setup issue",
                "evidence": [{"harness": "claude", "session_id": "abc", "anchor": 4}],
                "proposal": "Improve setup",
            }
        ],
        "project": [
            {
                "title": "Project issue",
                "evidence": [{"harness": "codex", "session_id": "def", "anchor": 8}],
                "proposal": "Improve project",
            }
        ],
    }
    report = render_report(findings, run_date=date(2026, 10, 23))
    assert "## Varde setup" in report
    assert "## Project" in report
    assert "claude/abc#4" in report
    assert "codex/def#8" in report
    path = write_report(tmp_path, date(2026, 10, 23), report)
    assert path == tmp_path / "reviews" / "2026-10-23.md"
    assert path.read_text() == report


def test_secret_is_redacted_from_report_and_friction_evidence():
    finding = {
        "category": "project",
        "title": f"Issue {SECRET}",
        "proposal": f"Use {SECRET}",
        "evidence": [{"session_id": SECRET}],
    }
    report = render_report(
        {"setup": [], "project": [finding]}, run_date=date(2026, 10, 23)
    )
    evidence = friction_evidence(finding)
    assert SECRET not in report
    assert SECRET not in evidence
    assert "review-key:" in evidence


def test_friction_key_is_stable_for_duplicates():
    finding = {"category": "setup", "title": "Repeated issue", "proposal": "Fix it"}
    assert review_friction_key(finding) == review_friction_key(dict(finding))


def test_friction_candidates_filter_existing_review_keys():
    finding = {"title": "Existing", "proposal": "Fix it", "evidence": []}
    key = review_friction_key({**finding, "category": "project"})
    candidates = friction_candidates({"project": [finding]}, {key})
    assert candidates == []
    fresh = friction_candidates({"project": [finding]}, set())
    assert len(fresh) == 1
    assert fresh[0]["review_key"] == key
