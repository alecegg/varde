from __future__ import annotations

from varde_workflow.handoff_format import validate
from varde_workflow.slot_handoff_render import render_handoff


def record() -> dict[str, object]:
    return {
        "role": "builder",
        "slot": {
            "slot_id": "durable-slot-resume-builder",
            "state": "active",
            "turn_count": 4,
        },
        "plan_id": "durable-slot-resume",
        "epoch": 3,
        "claimed_items": [
            {"id": f"task-{index}", "plan_dir": f"plans/task-{index}"}
            for index in range(1, 8)
        ],
        "last_progress": {"at": "2026-10-27T10:00:00Z", "note": "Updated tests"},
        "context_tokens": 250000,
        "recent_events": [],
        "task_states": [],
        "next_actions": [
            "Continue task-1",
            "Continue task-2",
            "Continue task-3",
            "Extra",
        ],
    }


def test_rendered_handoff_validates_and_resume_prompt_names_slot_epoch() -> None:
    rendered = render_handoff(record())
    result = validate(rendered.markdown, lambda _: True)

    assert result.errors == []
    assert "State:" in rendered.markdown
    assert "task-7" in rendered.markdown
    assert rendered.resume_prompt == (
        "Read this checkpoint, continue as builder in slot "
        "durable-slot-resume-builder epoch 3."
    )


def test_renderer_respects_section_limits() -> None:
    result = validate(render_handoff(record()).markdown, lambda _: True)
    assert result.errors == []
    assert len(result.summary) <= 120


def test_many_claims_are_summarized_and_preserved_in_record() -> None:
    handoff_record = record()
    claims = [
        {"id": f"task-{index}", "plan_dir": f"plans/task-{index}"}
        for index in range(1, 41)
    ]
    handoff_record["claimed_items"] = claims

    rendered = render_handoff(handoff_record)
    result = validate(rendered.markdown, lambda _: True)

    assert result.errors == []
    assert "and 32 more claims" in rendered.markdown
    assert rendered.record["claimed_items"] == claims
