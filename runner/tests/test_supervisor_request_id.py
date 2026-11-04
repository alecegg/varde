import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from varde_runner.plugins import RunnerCapabilities, SessionRef
from varde_runner.store import SessionStore
from varde_runner.supervisor import SendOutcome, Supervisor


class RequestPlugin:
    capabilities = RunnerCapabilities(idle_status=True)

    def __init__(self):
        self.sent: list[str] = []
        self.status = "idle"
        self.fail_next = False

    async def idle_status(self, ref):
        return self.status

    async def send(self, ref, prompt):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("temporary plugin failure")
        self.sent.append(prompt)

    async def close(self):
        pass


def make_supervisor(path: Path, plugin: RequestPlugin, *agents: str) -> Supervisor:
    supervisor = Supervisor(path, {"fake": plugin})
    for agent in agents:
        if supervisor.store.get_session(agent) is None:
            supervisor.store.create_session(
                agent,
                "fake",
                {"provider": "fake", "session_id": agent},
                "builder",
                agent_id=agent,
            )
        supervisor._refs[agent] = SessionRef("fake", agent)
    return supervisor


def test_repeated_request_id_returns_original_admission(tmp_path):
    async def run():
        plugin = RequestPlugin()
        supervisor = make_supervisor(tmp_path, plugin, "agent")
        first = await supervisor.send("agent", "first", request_id="request")
        repeated = await supervisor.send("agent", "second", request_id="request")
        assert first == repeated == SendOutcome.SENT
        assert plugin.sent == ["first"]
        await supervisor.shutdown()

    asyncio.run(run())


def test_busy_request_id_can_retry(tmp_path):
    async def run():
        plugin = RequestPlugin()
        supervisor = make_supervisor(tmp_path, plugin, "agent")
        plugin.status = "running"
        assert await supervisor.send("agent", "first", request_id="request") == (
            SendOutcome.SKIPPED_BUSY
        )
        plugin.status = "idle"
        assert await supervisor.send("agent", "retry", request_id="request") == (
            SendOutcome.SENT
        )
        assert plugin.sent == ["retry"]
        await supervisor.shutdown()

    asyncio.run(run())


def test_failed_request_id_can_retry(tmp_path):
    async def run():
        plugin = RequestPlugin()
        supervisor = make_supervisor(tmp_path, plugin, "agent")
        plugin.fail_next = True
        assert await supervisor.send("agent", "first", request_id="request") == (
            SendOutcome.FAILED
        )
        assert await supervisor.send("agent", "retry", request_id="request") == (
            SendOutcome.SENT
        )
        assert plugin.sent == ["retry"]
        await supervisor.shutdown()

    asyncio.run(run())


def test_request_ids_are_scoped_to_agent(tmp_path):
    async def run():
        plugin = RequestPlugin()
        supervisor = make_supervisor(tmp_path, plugin, "agent-a", "agent-b")
        assert await supervisor.send("agent-a", "a", request_id="request") == (
            SendOutcome.SENT
        )
        assert await supervisor.send("agent-b", "b", request_id="request") == (
            SendOutcome.SENT
        )
        assert plugin.sent == ["a", "b"]
        await supervisor.shutdown()

    asyncio.run(run())


def test_missing_request_id_keeps_each_send(tmp_path):
    async def run():
        plugin = RequestPlugin()
        supervisor = make_supervisor(tmp_path, plugin, "agent")
        assert await supervisor.send("agent", "first") == SendOutcome.SENT
        assert await supervisor.send("agent", "second") == SendOutcome.SENT
        assert plugin.sent == ["first", "second"]
        await supervisor.shutdown()

    asyncio.run(run())


def test_request_admission_survives_supervisor_restart(tmp_path):
    async def run():
        first_plugin = RequestPlugin()
        first_supervisor = make_supervisor(tmp_path, first_plugin, "agent")
        assert await first_supervisor.send("agent", "first", request_id="request") == (
            SendOutcome.SENT
        )
        await first_supervisor.shutdown()

        second_plugin = RequestPlugin()
        second_supervisor = make_supervisor(tmp_path, second_plugin, "agent")
        assert (
            await second_supervisor.send("agent", "second", request_id="request")
            == SendOutcome.SENT
        )
        assert second_plugin.sent == []
        await second_supervisor.shutdown()

    asyncio.run(run())


def test_version_five_store_gets_send_admissions_on_open(tmp_path):
    store = SessionStore(tmp_path)
    store.connection.execute("DROP TABLE send_admissions")
    store.connection.execute("PRAGMA user_version = 5")
    store.connection.commit()
    store.close()

    upgraded = SessionStore(tmp_path)
    version = upgraded.connection.execute("PRAGMA user_version").fetchone()[0]
    table = upgraded.connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name = 'send_admissions'"
    ).fetchone()
    assert version == 7
    assert table is not None
    upgraded.close()


def test_store_open_prunes_old_send_admissions(tmp_path):
    store = SessionStore(tmp_path)
    old_timestamp = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    store.connection.execute(
        "INSERT INTO send_admissions VALUES (?, ?, ?, ?)",
        ("agent", "old-request", SendOutcome.SENT, old_timestamp),
    )
    store.connection.commit()
    store.close()

    reopened = SessionStore(tmp_path)
    assert reopened.get_send_admission("agent", "old-request") is None
    reopened.close()
