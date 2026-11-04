from varde_runner.liveness import derive_liveness, is_agent_output, startup_phase


def test_startup_phase_boundaries_and_disabled_kill():
    assert startup_phase(2, 3, 5) == "wait"
    assert startup_phase(3, 3, 5) == "warn"
    assert startup_phase(5, 3, 5) == "kill"
    assert startup_phase(100, 3, 0) == "warn"


def test_agent_output_allow_list():
    for kind in ("text", "tool_intent", "tool_result", "permission_requested"):
        assert is_agent_output(kind, {})
    assert is_agent_output("session_end", {"status": "completed"})
    assert is_agent_output("session_end", {"status": "interrupted"})
    assert not is_agent_output("session_end", {"status": "failed"})
    assert not is_agent_output("status", {})
    assert not is_agent_output("usage", {})


def test_derive_liveness_rules() -> None:
    def derive(**values):
        args = {
            "lifecycle": "running",
            "idle_status": "running",
            "last_event_age_s": 1,
            "process_alive": True,
            "pending_approvals": 0,
            "stall_after_s": 10,
        }
        args.update(values)
        return derive_liveness(**args)

    assert derive(lifecycle="completed").state == "closed"
    assert derive(lifecycle="archived").state == "closed"
    assert derive(idle_status="closed").state == "closed"
    assert derive(lifecycle="failed").state == "error"
    assert derive(pending_approvals=1).state == "waiting"
    assert derive(idle_status="idle", process_alive=False).state == "idle"
    assert derive(process_alive=False).reason == "process_gone"
    assert derive(last_event_age_s=11, process_alive=None).reason == "silent"
    assert derive(process_alive=None).state == "running"
