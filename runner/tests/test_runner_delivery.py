from __future__ import annotations

import asyncio
import json
import multiprocessing
from pathlib import Path

import pytest
from varde_runner.delivery import DeliveryLoop
from varde_runner.harness_map import paseo_settings
from varde_runner.registry import SessionBinding, SessionRegistry
from varde_runner.supervisor import SendOutcome


class FakeAdapter:
    def __init__(self, status: str = "idle") -> None:
        self.status = status
        self.sent: list[tuple[str, str]] = []

    async def is_idle(self, session_id: str, harness: str | None = None) -> bool:
        return self.status == "idle"

    async def send(
        self, session_id: str, prompt: str, harness: str | None = None
    ) -> SendOutcome:
        if self.status != "idle":
            return SendOutcome.SKIPPED_BUSY
        self.sent.append((session_id, prompt))
        return SendOutcome.SENT


def test_registry_binds_first_prompt_marker_and_reloads(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    binding = SessionBinding(
        "plan-a", "codex-app-server", "paseo", "agent-a", "builder"
    )
    marker = "[varde-address: plan-a vt1." + "A" * 26 + "]"

    registry.expect_marker(marker)
    assert registry.bind_first_prompt(f"startup\n{marker}\nDo the task", binding)
    assert not registry.bind_first_prompt(
        "line 1\nline 2\nline 3\nline 4\nline 5\n"
        "[varde-address: plan-b vt1." + "A" * 26 + "]",
        binding,
    )
    assert SessionRegistry(tmp_path / "registry.json").resolve("plan-a") == binding


def test_unissued_marker_does_not_bind_even_when_its_token_is_well_formed(
    tmp_path: Path,
) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    binding = SessionBinding(
        "plan-a", "codex-app-server", "paseo", "agent-a", "builder"
    )
    unissued = "[varde-address: plan-a vt1." + "B" * 26 + "]"

    assert not registry.bind_first_prompt(unissued, binding)
    assert registry.resolve("plan-a") is None


def test_malformed_marker_token_cannot_be_issued(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")

    with pytest.raises(ValueError, match="invalid Varde address marker"):
        registry.expect_marker("[varde-address: plan-a not-a-token]")


def test_registry_reads_previous_provider_field_as_adapter(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "plan-a": {
                    "address": "plan-a",
                    "harness": "codex-app-server",
                    "provider": "paseo",
                    "session_id": "agent-a",
                    "role": "builder",
                    "plan_id": None,
                }
            }
        ),
        encoding="utf-8",
    )

    assert SessionRegistry(path).resolve("plan-a") == SessionBinding(
        "plan-a", "codex-app-server", "paseo", "agent-a", "builder"
    )


def test_delivery_holds_running_unknown_and_sends_idle_once(tmp_path: Path) -> None:
    async def exercise() -> None:
        registry = SessionRegistry(tmp_path / "registry.json")
        registry.register(
            SessionBinding("plan-a", "codex-app-server", "paseo", "agent-a", "builder")
        )
        adapter = FakeAdapter("running")
        messages = [{"id": "m1", "to": "plan-a", "text": "hello", "kind": "info"}]
        loop = DeliveryLoop(
            tmp_path / "deliveries.jsonl",
            registry,
            adapter,
            lambda: messages,
        )
        assert await loop.deliver_once() == 0
        assert adapter.sent == []
        assert not (tmp_path / "deliveries.jsonl").exists()
        adapter.status = "unknown"
        assert await loop.deliver_once() == 0
        assert not (tmp_path / "deliveries.jsonl").exists()
        adapter.status = "idle"
        assert await loop.deliver_once() == 1
        assert await loop.deliver_once() == 0
        assert adapter.sent == [("agent-a", "hello")]
        restarted = DeliveryLoop(
            tmp_path / "deliveries.jsonl",
            SessionRegistry(tmp_path / "registry.json"),
            adapter,
            lambda: messages,
        )
        assert await restarted.deliver_once() == 0

    asyncio.run(exercise())


def test_delivery_records_queued_as_accepted_without_releasing_claim(tmp_path: Path):
    class QueuedAdapter(FakeAdapter):
        async def send(
            self, session_id: str, prompt: str, harness: str | None = None
        ) -> SendOutcome:
            return SendOutcome.QUEUED

    async def exercise() -> None:
        registry = SessionRegistry(tmp_path / "registry.json")
        registry.register(
            SessionBinding("plan-a", "codex-app-server", "paseo", "agent-a", "builder")
        )
        log = tmp_path / "deliveries.jsonl"
        messages = [{"id": "m-queued", "to": "plan-a", "text": "hello"}]
        loop = DeliveryLoop(log, registry, QueuedAdapter(), lambda: messages)

        assert await loop.deliver_once() == 1
        assert await loop.deliver_once() == 0
        events = [json.loads(line) for line in log.read_text().splitlines()]
        assert [event["event"] for event in events] == ["claimed", "pushed"]

    asyncio.run(exercise())


def test_failed_send_releases_claim_and_loop_delivers_later_messages(
    tmp_path: Path,
) -> None:
    class FailOnceAdapter(FakeAdapter):
        failed = False

        async def send(
            self, session_id: str, prompt: str, harness: str | None = None
        ) -> SendOutcome:
            if prompt == "retry me" and not self.failed:
                self.failed = True
                return SendOutcome.FAILED
            return await super().send(session_id, prompt)

    async def exercise() -> None:
        registry = SessionRegistry(tmp_path / "registry.json")
        registry.register(
            SessionBinding("plan-a", "codex-app-server", "paseo", "agent-a", "builder")
        )
        messages = [
            {"id": "m1", "to": "plan-a", "text": "retry me"},
            {"id": "m2", "to": "plan-a", "text": "keep going"},
        ]
        adapter = FailOnceAdapter()
        log = tmp_path / "deliveries.jsonl"
        loop = DeliveryLoop(log, registry, adapter, lambda: messages)

        assert await loop.deliver_once() == 1
        events = [json.loads(line) for line in log.read_text().splitlines()]
        assert [(event["event"], event["message_id"]) for event in events] == [
            ("claimed", "m1"),
            ("claim_failed", "m1"),
            ("claimed", "m2"),
            ("pushed", "m2"),
        ]
        assert await loop.deliver_once() == 1
        assert adapter.sent == [
            ("agent-a", "keep going"),
            ("agent-a", "retry me"),
        ]

    asyncio.run(exercise())


def test_missing_adapter_raises_clear_delivery_error(tmp_path: Path) -> None:
    class Missing:
        async def is_idle(self, session_id, harness=None):
            return False

        async def send(self, session_id, prompt, harness=None):
            raise AssertionError("missing target must not send")

    registry = SessionRegistry(tmp_path / "registry.json")
    registry.register(
        SessionBinding("plan-a", "codex-app-server", "missing", "agent-a", "builder")
    )
    loop = DeliveryLoop(
        tmp_path / "deliveries.jsonl",
        registry,
        Missing(),
        lambda: [{"id": "m1", "to": "plan-a", "text": "hello"}],
    )

    assert asyncio.run(loop.deliver_once()) == 0


def test_stub_hook_provider_and_two_processes_produce_one_push(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    registry = SessionRegistry(registry_path)
    registry.register(
        SessionBinding("plan-a", "codex-app-server", "paseo", "agent-a", "builder")
    )
    path = tmp_path / "deliveries.jsonl"
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_run_delivery_process,
            args=(path, registry_path, barrier, results),
        )
        for _ in range(2)
    ]

    for process in processes:
        process.start()
    counts = [results.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert sum(counts) == 1
    assert sum(event["event"] == "pushed" for event in events) == 1


class _StubHookProvider:
    def __call__(self) -> list[dict[str, str]]:
        return [{"id": "m1", "to": "plan-a", "text": "hello"}]


class _ProcessAdapter:
    async def is_idle(self, session_id: str, harness: str | None = None) -> bool:
        return True

    async def send(
        self, session_id: str, prompt: str, harness: str | None = None
    ) -> SendOutcome:
        await asyncio.sleep(0.05)
        return SendOutcome.SENT


def _run_delivery_process(path, registry_path, barrier, results) -> None:
    loop = DeliveryLoop(
        path,
        SessionRegistry(registry_path),
        _ProcessAdapter(),
        _StubHookProvider(),
    )
    barrier.wait(timeout=15)
    results.put(asyncio.run(loop.deliver_once()))


def test_harness_map_passes_provider_model_mode_and_thinking_setting() -> None:
    settings = paseo_settings(
        {
            "harness": "codex-app-server",
            "model": "gpt-6-luna",
            "reasoning_effort": "low",
            "mode": "auto",
        }
    )

    assert settings == {
        "paseo_provider": "codex",
        "model": "gpt-6-luna",
        "thinking_option_id": "low",
        "mode_id": "auto",
    }


@pytest.mark.parametrize(
    ("harness", "runner_mode", "paseo_mode"),
    [
        ("codex-app-server", "auto", "auto"),
        ("codex-app-server", "workspace-write", "auto"),
        ("codex-app-server", "full-access", "full-access"),
        ("codex-app-server", "danger-full-access", "full-access"),
        ("claude-sdk", "auto", "auto"),
        ("claude-sdk", "read-only", "plan"),
        ("claude-sdk", "workspace-write", "acceptEdits"),
        ("claude-sdk", "full-access", "bypassPermissions"),
        ("claude-sdk", "danger-full-access", "bypassPermissions"),
        ("pi", "workspace-write", "workspace-write"),
    ],
)
def test_harness_map_translates_runner_modes(harness, runner_mode, paseo_mode):
    assert (
        paseo_settings(
            {"harness": harness, "model": "gpt-6-luna", "mode": runner_mode}
        )["mode_id"]
        == paseo_mode
    )


def test_harness_map_rejects_unknown_runner_mode():
    with pytest.raises(ValueError, match="unsupported runner mode"):
        paseo_settings(
            {"harness": "codex-app-server", "model": "gpt-6-luna", "mode": "unsafe"}
        )


def test_harness_map_rejects_codex_read_only_mode():
    with pytest.raises(ValueError, match="no Paseo equivalent"):
        paseo_settings(
            {
                "harness": "codex-app-server",
                "model": "gpt-6-luna",
                "mode": "read-only",
            }
        )


def test_harness_map_rejects_sol_models() -> None:
    with pytest.raises(ValueError, match="sol models are prohibited"):
        paseo_settings({"harness": "codex-app-server", "model": "gpt-6-sol"})


def test_harness_map_allows_non_sol_model_with_sol_prefix_substring() -> None:
    assert (
        paseo_settings({"harness": "codex-app-server", "model": "gpt-6-solar"})["model"]
        == "gpt-6-solar"
    )
