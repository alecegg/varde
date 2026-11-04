from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

from varde_data.records.chat import ChatBot
from varde_data.repos.chat import ChatRepository
from varde_runner.bot_lifecycle import (
    LifecycleHooks,
    ManagerBotLifecycle,
    latest_handoff,
)
from varde_runner.bot_profile import PROFILE_RESTRICTED, profile_for_role
from varde_runner.config import default_config

HANDOFF = """Summary: Continue the manager bot session.
Goal: Manage the user's dashboard requests.
Context: The runner owns the restricted manager session.
State:
- Generation 1 is idle.
Next:
- Start generation 2 with this handoff.
Open: None.
Reading list: None.
Pointers: None.
Do not redo: None.
"""


def test_manager_role_is_opt_in_and_uses_restricted_profile():
    role = default_config().resolve("manager-bot")
    assert role.enabled is False
    assert profile_for_role("manager-bot") == PROFILE_RESTRICTED


class FakeChat:
    def __init__(self, current=None):
        self.current = current
        self.events = []
        self.messages = [
            SimpleNamespace(role="user", text=f"message {n}") for n in range(40)
        ]

    def get_chat_bot(self, _key):
        return self.current

    def set_chat_bot(
        self, key, agent_id, started_at, context_tokens, state, generation
    ):
        self.current = ChatBot(
            key, agent_id, started_at, context_tokens, state, generation
        )
        return self.current

    def page(self, _key, *, limit):
        return tuple(self.messages[-limit:])

    def append_event(self, *event):
        self.events.append(event)


class FakeSupervisor:
    def __init__(self, tokens=200_000, status="idle"):
        self.store = SimpleNamespace(
            recent_usage_payloads=lambda _session, _limit: [{"context_tokens": tokens}]
        )
        self.status = status
        self.stopped = []

    def resolve_session(self, agent_id):
        return {"id": agent_id, "lifecycle": "running"}

    async def target_idle_status(self, _agent_id):
        return self.status

    async def stop(self, agent_id, client_id):
        self.stopped.append((agent_id, client_id))


def test_latest_handoff_selects_and_validates_last_complete_section(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text(f"Earlier notes.\n{HANDOFF}", encoding="utf-8")
    assert latest_handoff(path) == HANDOFF.strip()


def test_start_launches_one_manager_generation(tmp_path):
    chat = FakeChat()
    supervisor = FakeSupervisor()
    launches = []

    async def launch(prompt):
        launches.append(prompt)
        return "bot-first"

    lifecycle = ManagerBotLifecycle(
        chat=cast("ChatRepository", chat),
        working_dir=tmp_path,
        hooks=LifecycleHooks(
            get_supervisor=lambda: _ready(supervisor),
            launch=launch,
            run_state=lambda: "running",
            commit_notes=lambda _path: _ready(None),
        ),
    )

    async def scenario():
        assert await lifecycle.start() == "bot-first"
        assert await lifecycle.start() == "bot-first"

    asyncio.run(scenario())
    assert chat.current is not None
    assert chat.current.generation == 1
    assert len(launches) == 1


def test_concurrent_start_launches_only_one_manager_generation(tmp_path):
    chat = FakeChat()
    supervisor = FakeSupervisor()
    launches = []

    async def launch(prompt):
        launches.append(prompt)
        await asyncio.sleep(0)
        return "bot-first"

    lifecycle = ManagerBotLifecycle(
        chat=cast("ChatRepository", chat),
        working_dir=tmp_path,
        hooks=LifecycleHooks(
            get_supervisor=lambda: _ready(supervisor),
            launch=launch,
            run_state=lambda: "running",
            commit_notes=lambda _path: _ready(None),
        ),
    )

    async def scenario():
        return await asyncio.gather(lifecycle.start(), lifecycle.start())

    assert asyncio.run(scenario()) == ["bot-first", "bot-first"]
    assert len(launches) == 1
    assert chat.current is not None and chat.current.generation == 1


def test_replacement_requires_threshold_idle_and_valid_handoff(tmp_path):
    notes = tmp_path / "session-notes/manager-bot/notes.md"
    notes.parent.mkdir(parents=True)
    notes.write_text(HANDOFF, encoding="utf-8")
    chat = FakeChat(ChatBot("main", "bot-old", "now", None, "running", 1))
    supervisor = FakeSupervisor(tokens=199_999)
    launches = []
    commits = []

    async def launch(prompt):
        launches.append(prompt)
        return "bot-new"

    async def commit(path):
        commits.append(path)

    lifecycle = ManagerBotLifecycle(
        chat=cast("ChatRepository", chat),
        working_dir=tmp_path,
        hooks=LifecycleHooks(
            get_supervisor=lambda: _ready(supervisor),
            launch=launch,
            run_state=lambda: "running",
            commit_notes=commit,
        ),
    )

    async def scenario():
        assert await lifecycle.replace_if_due() is False
        supervisor.store.recent_usage_payloads = lambda _session, _limit: [
            {"context_tokens": 200_000}
        ]
        supervisor.status = "busy"
        assert await lifecycle.replace_if_due() is False
        supervisor.status = "idle"
        assert await lifecycle.replace_if_due() is True

    asyncio.run(scenario())
    assert chat.current is not None
    assert chat.current.agent_id == "bot-new"
    assert chat.current.generation == 2
    assert len(chat.events) == 1
    assert "Validated handoff" in launches[0]
    assert "message 10" in launches[0]
    assert "message 9" not in launches[0]
    assert commits == [notes]
    assert supervisor.stopped == [("bot-old", "system:manager-lifecycle")]


async def _ready(value):
    return value
