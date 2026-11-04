import asyncio

from varde_runner.events import RunnerEvent
from varde_runner.plugins import RunnerCapabilities
from varde_runner.supervisor import Supervisor


class FakePlugin:
    capabilities = RunnerCapabilities(resume=True, idle_status=True)

    def __init__(self, *, fail_resume=False, fail_send=False, emit_event=False):
        self.fail_resume = fail_resume
        self.fail_send = fail_send
        self.emit_event = emit_event
        self.resume_calls = 0

    async def resume(self, ref):
        self.resume_calls += 1
        if self.fail_resume:
            raise RuntimeError("crashed")
        return ref

    async def events(self, ref):
        if self.emit_event:
            yield RunnerEvent("text", ref.session_id, {"text": "send-resumed event"})
        if False:
            yield

    async def send(self, ref, prompt):
        if self.fail_send:
            raise RuntimeError("send failed")

    async def idle_status(self, ref):
        return "idle"

    async def close(self):
        return None


def _session(supervisor):
    supervisor.store.create_session(
        "session", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
    )


def test_crash_loop_parks_at_restart_limit(tmp_path):
    plugin = FakePlugin()
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    _session(supervisor)

    async def restart_until_parked():
        for _ in range(3):
            await supervisor.start()

    asyncio.run(restart_until_parked())

    assert plugin.resume_calls == 2
    row = supervisor.store.get_session("session")
    assert row is not None
    assert row["no_progress_restarts"] == 3
    assert row["lifecycle"] == "failed"
    events = supervisor.store.events_after("session", 0)
    assert [event["kind"] for event in events] == ["resume", "resume", "parked"]
    supervisor.store.close()


def test_parked_session_stays_parked_until_successful_send(tmp_path):
    plugin = FakePlugin()
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    _session(supervisor)

    async def park_then_restart():
        for _ in range(3):
            await supervisor.start()
        prior_events = supervisor.store.events_after("session", 0)
        await supervisor.start()
        assert supervisor.store.events_after("session", 0) == prior_events
        assert await supervisor.target_idle_status("session") == "error"
        assert plugin.resume_calls == 2
        assert supervisor.store.events_after("session", 0) == prior_events
        row = supervisor.store.get_session("session")
        assert row is not None
        assert row["no_progress_restarts"] == 3

    asyncio.run(park_then_restart())
    assert plugin.resume_calls == 2
    assert asyncio.run(supervisor.send("session", "continue")).value == "sent"
    assert plugin.resume_calls == 3
    row = supervisor.store.get_session("session")
    assert row is not None
    assert row["no_progress_restarts"] == 0
    supervisor.store.close()


def test_send_resumed_session_logs_plugin_events(tmp_path):
    plugin = FakePlugin(emit_event=True)
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    _session(supervisor)

    async def send_and_wait_for_events():
        outcome = await supervisor.send("session", "continue")
        await asyncio.gather(*supervisor._event_tasks)
        return outcome

    assert asyncio.run(send_and_wait_for_events()).value == "sent"
    assert [event["kind"] for event in supervisor.store.events_after("session", 0)] == [
        "resume",
        "text",
    ]
    supervisor.store.close()


def test_real_event_between_restarts_resets_count(tmp_path):
    plugin = FakePlugin()
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    _session(supervisor)

    async def restart_with_progress():
        await supervisor.start()
        row = supervisor.store.get_session("session")
        assert row is not None
        assert row["no_progress_restarts"] == 1
        await supervisor.record_event("session", "text", {"text": "progress"})
        await supervisor.start()

    asyncio.run(restart_with_progress())

    row = supervisor.store.get_session("session")
    assert row is not None
    assert row["no_progress_restarts"] == 0
    assert row["lifecycle"] == "running"
    assert plugin.resume_calls == 2
    supervisor.store.close()


def test_supervisor_events_do_not_count_as_restart_progress(tmp_path):
    plugin = FakePlugin()
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    _session(supervisor)

    async def restart_with_bookkeeping_events():
        await supervisor.start()
        for kind in ("status", "usage", "warning", "error", "activity"):
            await supervisor.record_event("session", kind, {"status": "running"})
        await supervisor.start()

    asyncio.run(restart_with_bookkeeping_events())

    row = supervisor.store.get_session("session")
    assert row is not None
    assert row["no_progress_restarts"] == 2
    supervisor.store.close()


def test_failed_send_does_not_reset_restart_count(tmp_path):
    plugin = FakePlugin(fail_send=True)
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    _session(supervisor)

    async def prepare_parked():
        for _ in range(3):
            await supervisor.start()

    asyncio.run(prepare_parked())

    assert asyncio.run(supervisor.send("session", "continue")).value == "failed"
    row = supervisor.store.get_session("session")
    assert row is not None
    assert row["no_progress_restarts"] == 3
    supervisor.store.close()


def test_quiet_idle_restart_keeps_count_and_resumes_past_limit(tmp_path):
    plugin = FakePlugin()
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    _session(supervisor)
    seq = supervisor.store.append_event("session", "status", {"status": "idle"})
    supervisor.store.update_session(
        "session", no_progress_restarts=5, seq_at_last_start=seq
    )

    async def restart_repeatedly():
        for _ in range(3):
            await supervisor.start()

    asyncio.run(restart_repeatedly())

    row = supervisor.store.get_session("session")
    assert row is not None
    assert row["no_progress_restarts"] == 5
    assert plugin.resume_calls == 3
    events = supervisor.store.events_after("session", 0)
    assert [event["kind"] for event in events] == [
        "status",
        "resume",
        "resume",
        "resume",
    ]
    supervisor.store.close()


def test_running_status_still_parks_at_restart_limit(tmp_path):
    plugin = FakePlugin()
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    _session(supervisor)
    seq = supervisor.store.append_event("session", "status", {"status": "running"})
    supervisor.store.update_session(
        "session", no_progress_restarts=2, seq_at_last_start=seq
    )

    asyncio.run(supervisor.start())

    row = supervisor.store.get_session("session")
    assert row is not None
    assert row["no_progress_restarts"] == 3
    assert row["lifecycle"] == "failed"
    events = supervisor.store.events_after("session", 0)
    assert events[-1]["kind"] == "parked"
    assert plugin.resume_calls == 0
    supervisor.store.close()


def test_open_intent_prevents_idle_restart_exemption(tmp_path):
    plugin = FakePlugin()
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    _session(supervisor)
    supervisor.store.append_event("session", "status", {"status": "idle"})
    intent_seq = supervisor.store.append_event(
        "session", "tool_intent", {"call_id": "open", "name": "shell"}
    )
    supervisor.store.update_session(
        "session", no_progress_restarts=2, seq_at_last_start=intent_seq
    )

    asyncio.run(supervisor.start())

    row = supervisor.store.get_session("session")
    assert row is not None
    assert row["lifecycle"] == "failed"
    assert supervisor.store.events_after("session", 0)[-1]["kind"] == "parked"
    assert plugin.resume_calls == 0
    supervisor.store.close()


def test_failed_resume_counts_restart(tmp_path):
    plugin = FakePlugin(fail_resume=True)
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    _session(supervisor)
    seq = supervisor.store.append_event("session", "status", {"status": "running"})
    supervisor.store.update_session("session", seq_at_last_start=seq)

    asyncio.run(supervisor.start())

    row = supervisor.store.get_session("session")
    assert row is not None
    assert row["no_progress_restarts"] == 1
    assert plugin.resume_calls == 1
    supervisor.store.close()


def test_quiet_idle_failed_resume_parks_at_restart_limit(tmp_path):
    plugin = FakePlugin(fail_resume=True)
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    _session(supervisor)
    seq = supervisor.store.append_event("session", "status", {"status": "idle"})
    supervisor.store.update_session(
        "session", no_progress_restarts=2, seq_at_last_start=seq
    )

    asyncio.run(supervisor.start())

    row = supervisor.store.get_session("session")
    assert row is not None
    assert row["no_progress_restarts"] == 3
    assert row["lifecycle"] == "failed"
    assert supervisor.store.events_after("session", 0)[-1]["kind"] == "parked"
    assert plugin.resume_calls == 1
    supervisor.store.close()


def test_older_parked_idle_session_stays_parked(tmp_path):
    plugin = FakePlugin()
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    _session(supervisor)
    supervisor.store.append_event("session", "status", {"status": "idle"})
    supervisor.store.update_session("session", status="error", no_progress_restarts=3)
    prior_events = supervisor.store.events_after("session", 0)

    asyncio.run(supervisor.start())

    assert supervisor.store.events_after("session", 0) == prior_events
    assert plugin.resume_calls == 0
    supervisor.store.close()


def test_error_status_counts_toward_restart_limit(tmp_path):
    plugin = FakePlugin()
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    _session(supervisor)
    seq = supervisor.store.append_event("session", "status", {"status": "error"})
    supervisor.store.update_session(
        "session", status="error", no_progress_restarts=2, seq_at_last_start=seq
    )

    asyncio.run(supervisor.start())

    row = supervisor.store.get_session("session")
    assert row is not None
    assert row["no_progress_restarts"] == 3
    assert row["lifecycle"] == "failed"
    assert supervisor.store.events_after("session", 0)[-1]["kind"] == "parked"
    assert plugin.resume_calls == 0
    supervisor.store.close()
