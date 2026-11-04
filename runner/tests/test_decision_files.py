from __future__ import annotations

import json

import pytest
from varde_runner.decision_files import decision_file_items


@pytest.mark.parametrize(
    "decision_type",
    ["design", "choice", "decision", "approval", "design_decision", "question"],
)
def test_unanswered_file_projects_and_mail_dedupes(tmp_path, decision_type):
    plan_dir = tmp_path / "plan"
    notes = plan_dir / "notes"
    notes.mkdir(parents=True)
    path = notes / "decision-question.json"
    path.write_text(
        json.dumps(
            {
                "type": decision_type,
                "asked": "Choose a direction",
                "why": "Needed to proceed",
                "options": [{"id": "a", "label": "Option A"}],
                "recommendation": "a",
            }
        ),
        encoding="utf-8",
    )
    plans = [
        {
            "id": "plan-1",
            "status": "active",
            "directory": plan_dir,
            "assigned_to": "orchestrator-1",
        }
    ]

    item = decision_file_items(plans, [])[0]
    assert item["type"] == decision_type
    assert item["sender"] == "orchestrator-1"
    assert item["options"] == [{"id": "a", "label": "Option A"}]
    assert item["recommendation"] == "a"
    assert item["notes"] == str(path.resolve())
    assert decision_file_items(plans, [{"notes": str(path.resolve())}]) == []


def test_relative_mail_notes_are_resolved_against_plan_directory(tmp_path):
    plan_dir = tmp_path / "plan"
    notes = plan_dir / "notes"
    notes.mkdir(parents=True)
    path = notes / "decision-question.json"
    path.write_text(
        json.dumps({"type": "design_decision", "options": ["a"]}),
        encoding="utf-8",
    )
    plans = [{"directory": plan_dir, "status": "active", "assigned_to": "orch"}]
    assert decision_file_items(plans, [{"notes": "notes/decision-question.json"}]) == []


@pytest.mark.parametrize("mail_state", ["answered", "acknowledged"])
def test_historic_answer_or_ack_suppresses_file_card(tmp_path, mail_state):
    plan_dir = tmp_path / "plan"
    notes = plan_dir / "notes"
    notes.mkdir(parents=True)
    path = notes / "decision-question.json"
    path.write_text(
        json.dumps({"type": "question", "options": ["a"]}), encoding="utf-8"
    )
    message = {"id": "mail-1", "notes": str(path)}
    if mail_state == "answered":
        message["reply"] = "a"
        acknowledged = set()
    else:
        acknowledged = {"mail-1"}
    assert (
        decision_file_items(
            [{"directory": plan_dir, "status": "active", "assigned_to": "orch"}],
            [],
            [message],
            acknowledged,
        )
        == []
    )


def test_merge_decision_file_is_projected(tmp_path):
    plan_dir = tmp_path / "plan"
    notes = plan_dir / "notes"
    notes.mkdir(parents=True)
    path = notes / "merge-decision.json"
    path.write_text(
        json.dumps({"type": "approval", "options": ["approve"]}),
        encoding="utf-8",
    )
    result = decision_file_items(
        [{"directory": plan_dir, "status": "active", "assigned_to": "orch"}],
        [],
    )
    assert len(result) == 1
    assert result[0]["notes"] == str(path.resolve())


def test_answered_and_terminal_plan_files_are_omitted(tmp_path):
    plan_dir = tmp_path / "plan"
    notes = plan_dir / "notes"
    notes.mkdir(parents=True)
    (notes / "decision-answered.json").write_text(
        json.dumps({"type": "choice", "options": ["a"], "answer": "a"}),
        encoding="utf-8",
    )
    (notes / "decision-terminal.json").write_text(
        json.dumps({"type": "choice", "options": ["a"]}), encoding="utf-8"
    )
    assert (
        decision_file_items(
            [
                {
                    "directory": plan_dir,
                    "status": "completed",
                    "assigned_to": "orchestrator-1",
                }
            ],
            [],
        )
        == []
    )
