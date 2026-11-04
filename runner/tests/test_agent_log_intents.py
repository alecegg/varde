import asyncio

import pytest
from varde_runner.plugins import RunnerCapabilities
from varde_runner.supervisor import Supervisor


class FakePlugin:
    capabilities = RunnerCapabilities(resume=True)

    async def resume(self, ref):
        return ref

    async def events(self, ref):
        if False:
            yield

    async def close(self):
        return None


@pytest.mark.parametrize(
    ("intent_payload", "expected"),
    [
        (
            {"call_id": "call-1", "tool": "Read"},
            [{"call_id": "call-1", "tool": "Read"}],
        ),
        ({"call_id": "legacy-call"}, [{"call_id": "legacy-call", "tool": None}]),
        (None, []),
    ],
)
def test_resume_event_reports_open_intents(tmp_path, intent_payload, expected):
    supervisor = Supervisor(tmp_path, {"fake": FakePlugin()})
    supervisor.store.create_session(
        "session", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
    )
    if intent_payload is not None:
        supervisor.store.append_event("session", "tool_intent", intent_payload)

    asyncio.run(supervisor.start())

    resume_events = [
        event
        for event in supervisor.store.events_after("session", 0)
        if event["kind"] == "resume"
    ]
    assert resume_events[0]["payload"]["open_intents"] == expected
    supervisor.store.close()
