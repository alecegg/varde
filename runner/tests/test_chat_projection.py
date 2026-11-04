from __future__ import annotations

from varde_runner.chat_projection import project_event


def event(seq, kind, payload=None, agent_id="manager"):
    return {"seq": seq, "kind": kind, "payload": payload or {}, "agent_id": agent_id}


def test_main_projects_only_events_in_the_recorded_chat_turn():
    assert (
        project_event(
            "main",
            turn_agent_id="manager",
            first_event_seq=10,
            event=event(9, "text", {"text": "relay output"}),
        )
        is None
    )
    assert (
        project_event(
            "main",
            turn_agent_id="manager",
            first_event_seq=10,
            event=event(11, "text", {"text": "other target"}, agent_id="other"),
        )
        is None
    )
    delta = project_event(
        "main",
        turn_agent_id="manager",
        first_event_seq=10,
        event=event(10, "text_delta", {"text": "Hello"}),
    )
    assert delta is not None and delta.action == "delta"
    text = project_event(
        "main",
        turn_agent_id="manager",
        first_event_seq=10,
        event=event(12, "text", {"text": "Hello world"}),
    )
    assert text is not None and text.action == "text"


def test_projection_accepts_thread_kind_and_ignores_unimplemented_instance_kind():
    assert (
        project_event(
            "instance",
            turn_agent_id="worker",
            first_event_seq=1,
            event=event(1, "text", {"text": "whole session"}, agent_id="worker"),
        )
        is None
    )


def test_idle_and_session_end_close_a_streaming_row():
    for item in (event(20, "session_end"), event(20, "status", {"status": "idle"})):
        projected = project_event(
            "main", turn_agent_id="manager", first_event_seq=20, event=item
        )
        assert projected is not None and projected.action == "finish"
