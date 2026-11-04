from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from varde_runner.config import default_toml
from varde_runner.events import RunnerEvent
from varde_runner.plugins import RunnerCapabilities, SessionRef
from varde_runner.registry import SessionRegistry
from varde_runner.supervisor import Supervisor
from varde_runner.workitems import WorkItemStore


def codex_planner_toml() -> str:
    text = default_toml().replace(
        '[roles.planner]\ntype = "standard"',
        '[roles.planner]\ntype = "codex-planner"',
    )
    return (
        text
        + """
[types.codex-planner]
harness = "codex-app-server"
model = "gpt-6-luna"
reasoning_effort = "medium"

[[types.codex-planner.fallback]]
harness = "pi"
model = "deepseek/deepseek-v4-flash"
reasoning_effort = "high"
"""
    )


def codex_plugins(plugin: Any) -> dict[str, Any]:
    return dict.fromkeys(("claude-sdk", "codex-app-server", "pi"), plugin)


def test_submit_stores_full_text_and_starts_one_planner(tmp_path: Path) -> None:
    text = ("å🧭 line\r\n" * 2200)[:20_000]
    store = WorkItemStore(tmp_path)
    first = store.create("same-key", text, "project-a")
    second = store.create("same-key", text, "project-a")
    store.start_planning(first.id, "session-planner-1")

    assert first.id == second.id
    assert store.get(first.id).state == "planning"
    assert Path(first.notes_path).read_bytes() == text.encode("utf-8")
    assert store.get(first.id).planner_session == "session-planner-1"
    assert store.audit(first.id)[-1]["new_state"] == "planning"


def test_work_item_transitions_are_audited_and_terminal_decision_is_stable(
    tmp_path: Path,
) -> None:
    store = WorkItemStore(tmp_path)
    item = store.create("key", "describe the work", "project-a")
    store.start_planning(item.id, "planner-session")
    context = {
        "asked": "Which target?",
        "why": "Blocks plan",
        "options": [{"label": "A", "consequence": "Use A"}],
        "recommendation": {"label": "A", "reason": "Fits"},
        "sources": ["plan-a"],
    }
    assert store.question(item.id, "question-1", context)
    assert not store.question(item.id, "question-1", context)
    assert store.questions(item.id)[0]["payload"] == context
    assert store.answer(item.id, "question-1", "A", "answer-key")
    assert not store.answer(item.id, "question-1", "A", "answer-key")
    store.plan_ready(item.id, tmp_path / "plan.md", "plan-ready-1")
    store.reject(item.id)
    store.decide(item.id, True)

    current = store.get(item.id)
    assert current.state == "rejected"
    assert [row["new_state"] for row in store.audit(item.id)] == [
        "new",
        "planning",
        "asking",
        "planning",
        "ready",
        "rejected",
    ]
    assert current.plan_ready_id == "plan-ready-1"


def test_rejects_text_over_limit_without_creating_item(tmp_path: Path) -> None:
    store = WorkItemStore(tmp_path)
    with pytest.raises(ValueError, match="20,000"):
        store.create("key", "x" * 20_001, "project-a")
    assert store.list() == []


def test_approval_queues_and_plan_ready_is_idempotent(tmp_path: Path) -> None:
    store = WorkItemStore(tmp_path)
    item = store.create("key", "request", "project")
    store.start_planning(item.id, "planner")
    first = store.plan_ready(item.id, tmp_path / "plan.md", "plan-ready-1")
    repeated = store.plan_ready(item.id, tmp_path / "other.md", "plan-ready-2")
    assert first.plan_ready_id == repeated.plan_ready_id == "plan-ready-1"
    queued = store.decide(item.id, True)
    assert queued.state == "queued"
    assert [row["new_state"] for row in store.audit(item.id)] == [
        "new",
        "planning",
        "ready",
        "queued",
    ]


def test_supervisor_starts_and_binds_planner_role_from_config(tmp_path: Path) -> None:
    class FakePlugin:
        capabilities = RunnerCapabilities(resume=True, idle_status=True)

        async def start(self, spec):
            self.spec = spec
            return SessionRef(spec.provider, "remote-planner")

        async def resume(self, ref):
            return ref

        async def events(self, ref):
            await asyncio.Event().wait()
            yield RunnerEvent("status", "remote-planner")

        async def close(self):
            return None

        async def send(self, ref, prompt):
            return None

        async def respond_permission(self, ref, request_id, decision):
            return None

        async def stop(self, ref):
            return None

    async def run() -> None:
        plugin = FakePlugin()
        config_path = tmp_path / "runner.toml"
        config_path.write_text(codex_planner_toml(), encoding="utf-8")
        notes = tmp_path / "request.md"
        notes.write_bytes("full 🧭 request\r\n".encode())
        supervisor = Supervisor(tmp_path / "data", {"codex": plugin})
        session = await supervisor.start_planner_session(
            "item-123", notes, str(tmp_path), config_path
        )
        try:
            assert plugin.spec.model == "gpt-6-luna"
            assert plugin.spec.provider == "codex"
            assert str(notes) in plugin.spec.prompt
            assert "Your sender address is workitem-item-123." in plugin.spec.prompt
            assert (
                "varde msg send --from workitem-item-123 --to main --kind needs-user"
                in plugin.spec.prompt
            )
            assert (
                "plan-ready message using the same command with --kind needs-user"
                in plugin.spec.prompt
            )
            assert plugin.spec.prompt.count("exactly one") == 1
            binding = SessionRegistry(tmp_path / "data" / "registry.json").resolve(
                "item-123"
            )
            assert binding is not None
            assert binding.role == "planner"
            assert binding.session_id == "remote-planner"
            assert session.session_id != binding.session_id
        finally:
            await supervisor.shutdown()

    asyncio.run(run())


def test_asking_question_survives_store_restart_without_duplicate(
    tmp_path: Path,
) -> None:
    store = WorkItemStore(tmp_path)
    item = store.create("key", "request", "project")
    store.start_planning(item.id, "planner")
    context = {
        "asked": "Which?",
        "why": "Blocks",
        "options": [{"label": "A", "consequence": "Use A"}],
        "recommendation": "A",
        "sources": [],
    }
    assert store.question(item.id, "question-1", context)
    store.close()
    restarted = WorkItemStore(tmp_path)
    assert restarted.get(item.id).state == "asking"
    assert len(restarted.questions(item.id)) == 1
    assert not restarted.question(item.id, "question-1", context)
    restarted.close()


def test_plan_ready_message_with_done_kind_is_synced(tmp_path: Path) -> None:
    store = WorkItemStore(tmp_path)
    item = store.create("plan-ready-kind", "request", "project")
    store.start_planning(item.id, "planner")
    address = f"workitem-{item.id[:40]}"
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("Plan", encoding="utf-8")
    notes_path = tmp_path / "plan-ready.json"
    notes_path.write_text(
        json.dumps({"work_item_event": "plan_ready", "plan_path": str(plan_path)}),
        encoding="utf-8",
    )

    assert store.sync_message(
        {
            "id": "plan-ready-done",
            "from": address,
            "kind": "done",
            "notes": str(notes_path),
        },
        address,
    )
    assert store.get(item.id).state == "ready"
    store.close()


def test_question_message_with_done_kind_is_not_synced(tmp_path: Path) -> None:
    store = WorkItemStore(tmp_path)
    item = store.create("question-done-kind", "request", "project")
    store.start_planning(item.id, "planner")
    address = f"workitem-{item.id[:40]}"
    notes_path = tmp_path / "question.json"
    notes_path.write_text(json.dumps({"asked": "Choose?"}), encoding="utf-8")

    assert not store.sync_message(
        {
            "id": "question-done",
            "from": address,
            "kind": "done",
            "notes": str(notes_path),
        },
        address,
    )
    assert store.get(item.id).state == "planning"
    assert store.questions(item.id) == []
    store.close()


@pytest.mark.parametrize(
    "message_address",
    ["workitem-some-other-item", "builder"],
    ids=["mismatched-from", "non-workitem-address"],
)
def test_plan_ready_rejects_invalid_sender_address(
    tmp_path: Path, message_address: str
) -> None:
    store = WorkItemStore(tmp_path)
    item = store.create("invalid-plan-sender", "request", "project")
    store.start_planning(item.id, "planner")
    address = f"workitem-{item.id[:40]}"
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("Plan", encoding="utf-8")
    notes_path = tmp_path / "plan-ready.json"
    notes_path.write_text(
        json.dumps({"work_item_event": "plan_ready", "plan_path": str(plan_path)}),
        encoding="utf-8",
    )

    assert not store.sync_message(
        {
            "id": "invalid-plan-sender",
            "from": message_address,
            "kind": "done",
            "notes": str(notes_path),
        },
        address if message_address.startswith("workitem-") else message_address,
    )
    assert store.get(item.id).state == "planning"
    store.close()


def test_supervisor_restarts_unresumable_planner_with_prior_question(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakePlugin:
        capabilities = RunnerCapabilities(resume=False)

        def __init__(self) -> None:
            self.specs = []

        async def start(self, spec):
            self.specs.append(spec)
            return SessionRef(spec.provider, f"remote-{len(self.specs)}")

        async def resume(self, ref):
            raise AssertionError("resume is unavailable")

        async def events(self, ref):
            await asyncio.Event().wait()
            yield RunnerEvent("status", "remote-planner")

        async def close(self):
            return None

        async def send(self, ref, prompt):
            return None

        async def respond_permission(self, ref, request_id, decision):
            return None

        async def stop(self, ref):
            return None

    async def run() -> None:
        plugin = FakePlugin()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = config_dir / "runner.toml"
        config_path.write_text(codex_planner_toml(), encoding="utf-8")
        monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(config_dir))
        data_dir = tmp_path / "data"
        first = Supervisor(data_dir, codex_plugins(plugin))
        await first.start()
        store = WorkItemStore(data_dir)
        item = store.create("key", "request", "project")
        session = await first.start_planner_session(
            item.id, Path(item.notes_path), item.project, config_path
        )
        store.start_planning(item.id, session.session_id)
        store.question(
            item.id,
            "question-1",
            {
                "asked": "Which?",
                "why": "Blocks",
                "options": [{"label": "A", "consequence": "Use A"}],
                "recommendation": "A",
                "sources": [],
            },
        )
        store.close()
        await first.shutdown()

        second = Supervisor(data_dir, codex_plugins(plugin))
        await second.start()
        try:
            recovered = WorkItemStore(data_dir)
            current = recovered.get(item.id)
            assert current.state == "asking"
            assert current.planner_session != session.session_id
            assert len(recovered.questions(item.id)) == 1
            assert "question-1" in plugin.specs[-1].prompt
            recovered.close()
        finally:
            await second.shutdown()

    asyncio.run(run())


def test_duplicate_key_race_returns_one_item_and_removes_orphan_notes(
    tmp_path: Path, monkeypatch
) -> None:
    first = WorkItemStore(tmp_path)
    second = WorkItemStore(tmp_path)
    both_wrote = Barrier(2)
    write_bytes = Path.write_bytes

    def synchronized_write(path: Path, body: bytes) -> int:
        if path.name == "request.md" or path.parent.name == "workitem-notes":
            both_wrote.wait(timeout=5)
        return write_bytes(path, body)

    monkeypatch.setattr(Path, "write_bytes", synchronized_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(store.create, "same-key", f"body-{index}", "workspace")
            for index, store in enumerate((first, second))
        ]
        results = [future.result(timeout=10) for future in futures]
    assert results[0].id == results[1].id
    assert len(first.list()) == 1
    assert len(list((tmp_path / "workitem-notes").rglob("request.md"))) == 1


def test_supervisor_recovers_or_resets_durable_planner_start_intents(
    tmp_path: Path, monkeypatch
) -> None:
    class FakePlugin:
        capabilities = RunnerCapabilities(resume=True)

        def __init__(self) -> None:
            self.counter = 0

        async def start(self, spec):
            self.counter += 1
            return SessionRef(spec.provider, f"remote-{self.counter}")

        async def resume(self, ref):
            return ref

        async def events(self, ref):
            await asyncio.Event().wait()
            yield RunnerEvent("status", "remote-planner")

        async def close(self):
            return None

        async def send(self, ref, prompt):
            return None

        async def respond_permission(self, ref, request_id, decision):
            return None

        async def stop(self, ref):
            return None

    async def run() -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = config_dir / "runner.toml"
        config_path.write_text(codex_planner_toml(), encoding="utf-8")
        monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(config_dir))
        data_dir = tmp_path / "data"
        plugin = FakePlugin()
        first_supervisor = Supervisor(data_dir, codex_plugins(plugin))
        await first_supervisor.start()
        store = WorkItemStore(data_dir)
        bound = store.create("bound", "request", "workspace")
        store.claim_planner_start(bound.id)
        session = await first_supervisor.start_planner_session(
            bound.id, Path(bound.notes_path), bound.project, config_path
        )
        orphan = store.create("orphan", "request", "workspace")
        store.claim_planner_start(orphan.id)
        store.close()
        await first_supervisor.shutdown()

        restarted = Supervisor(data_dir, codex_plugins(plugin))
        await restarted.start()
        try:
            recovered = WorkItemStore(data_dir)
            assert recovered.get(bound.id).state == "planning"
            assert recovered.get(bound.id).planner_session == session.session_id
            assert recovered.get(orphan.id).state == "new"
            assert recovered.audit(orphan.id)[-1]["new_state"] == "new"
            recovered.close()
        finally:
            await restarted.shutdown()

    asyncio.run(run())
