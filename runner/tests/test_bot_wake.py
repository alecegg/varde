import asyncio
from types import SimpleNamespace
from typing import cast

from varde_runner.bot_wake import ManagerBotWake, manager_wake_prompt
from varde_runner.relay import RelayCLIProtocol, RelayWorker


def test_relay_wake_digest_is_coalesced_non_projecting_and_lists_stalls():
    action = {
        "action_id": "a1",
        "address": "manager",
        "message_ids": ["m1", "m2"],
        "prompt": "Varde messages for manager: m1, m2",
    }
    prompt = manager_wake_prompt(action, ["builder-2", "builder-1", "builder-2"])
    assert "m1, m2" in prompt
    assert "Stalled agents: builder-1, builder-2" in prompt
    assert "varde msg read --as manager" in prompt


def test_manager_wake_skips_while_paused_and_sends_one_unprojected_prompt():
    class FakeSupervisor:
        def __init__(self):
            self.sent = []
            self.store = SimpleNamespace(sessions=list)

        async def send(self, *args, **kwargs):
            self.sent.append((args, kwargs))
            return SimpleNamespace(value="sent")

    supervisor = FakeSupervisor()
    paused = [True]
    wake = ManagerBotWake(lambda: _ready(supervisor), paused=lambda: paused[0])
    action = {
        "action_id": "digest-1",
        "address": "manager",
        "message_ids": ["m1", "m2"],
        "prompt": "Varde messages for manager: m1, m2",
        "wake": {"agent_id": "manager-session", "harness": "claude-cli"},
    }

    async def scenario():
        assert await wake(action) == ("skipped-busy", "observed-result")
        assert supervisor.sent == []
        paused[0] = False
        assert await wake(action) == ("pushed", "successful-send")

    asyncio.run(scenario())
    assert len(supervisor.sent) == 1
    args, kwargs = supervisor.sent[0]
    assert args[0] == "manager-session"
    assert "m1, m2" in args[1]
    assert kwargs["request_id"] == "digest-1"
    assert kwargs["client_id"] == "system:relay"


def test_relay_routes_manager_slot_to_digest_handler():
    class FakeRelay:
        async def renew(self, _action_id):
            return {"status": "renewed"}

    received = []

    async def manager_wake(action):
        received.append(action)
        return "pushed", "successful-send"

    worker = RelayWorker(
        cast("RelayCLIProtocol", FakeRelay()), None, manager_wake=manager_wake
    )
    action = {"action_id": "digest", "address": "manager"}
    assert asyncio.run(worker.deliver(action)) == ("pushed", "successful-send")
    assert received == [action]


async def _ready(value):
    return value
