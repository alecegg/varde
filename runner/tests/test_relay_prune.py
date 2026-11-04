from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from varde_data.errors import Locked
from varde_data.relay_prune import prune_legacy_mailman_state as data_prune
from varde_runner import relay as relay_module
from varde_runner.relay import RelayWaitStopped, RelayWorker
from varde_runner.relay_prune import prune_legacy_mailman_state


def test_runner_relay_prune_import_remains_a_compatibility_alias() -> None:
    assert prune_legacy_mailman_state is data_prune


def _live_state() -> dict:
    fixture = Path(__file__).parent / "fixtures" / "relay-state-live-shapes.json"
    state = json.loads(fixture.read_text())
    tokens = [f"generation-{index:02}" for index in range(87)]
    state["current_mailman"] = tokens[-1]
    state["mailman_started"] = {
        token: f"2026-10-{index // 24 + 1:02}T{index % 24:02}:00:00Z"
        for index, token in enumerate(tokens)
    }
    state["mailman_instances"] = {token: f"runner:{token}" for token in tokens}
    state["cycles"] = {token: index for index, token in enumerate(tokens)}
    return state


def test_prunes_old_generations_with_backup_and_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / ".cache" / "inbox" / "relay"
    root.mkdir(parents=True)
    state_path = root / "state.json"
    original = _live_state()
    state_path.write_text(json.dumps(original))

    result = prune_legacy_mailman_state(
        tmp_path, now=datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    )

    assert result["pruned"] == 81
    assert result["kept"] == 6
    backups = list(root.glob("state.json.bak-*Z"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == original
    pruned = json.loads(state_path.read_text())
    kept = set(pruned["mailman_started"])
    assert kept == {f"generation-{index:02}" for index in range(81, 87)}
    assert set(pruned["mailman_instances"]) == kept
    assert set(pruned["cycles"]) == kept
    assert pruned["current_mailman"] == original["current_mailman"]
    assert pruned["events"] == original["events"]
    assert pruned["escalations"] == original["escalations"]

    second = prune_legacy_mailman_state(
        tmp_path, now=datetime(2026, 10, 24, 12, 1, tzinfo=UTC)
    )

    assert second["pruned"] == 0
    assert len(list(root.glob("state.json.bak-*Z"))) == 1


def test_prune_preserves_live_bound_and_referenced_generations(tmp_path: Path) -> None:
    root = tmp_path / ".cache" / "inbox" / "relay"
    root.mkdir(parents=True)
    original = _live_state()
    now = datetime(2026, 10, 24, 14, 0, tzinfo=UTC)
    original["events"].append(
        {"event": "waiting", "at": now.isoformat(), "token_id": "generation-00"}
    )
    original["leases"] = [{"action_id": "leased-action"}]
    original["attempts"] = {"message-id": [{"action_id": "attempted-action"}]}
    (root / "state.json").write_text(json.dumps(original))

    mailman = tmp_path / ".cache" / "inbox" / "addresses" / "mailman"
    mailman.mkdir(parents=True)
    (mailman / "current").write_text(json.dumps({"token_id": "generation-01"}))
    actions = root / "actions"
    actions.mkdir()
    (actions / "leased-action.json").write_text(
        json.dumps({"token_id": "generation-02"})
    )
    (actions / "attempted-action.json").write_text(
        json.dumps({"token_id": "generation-03"})
    )

    result = prune_legacy_mailman_state(tmp_path, now=now)

    assert result["pruned"] == 77
    kept = set(json.loads((root / "state.json").read_text())["mailman_started"])
    assert {f"generation-{index:02}" for index in range(4)} <= kept
    assert {f"generation-{index:02}" for index in range(81, 87)} <= kept


def test_prune_can_be_disabled(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / ".cache" / "inbox" / "relay"
    root.mkdir(parents=True)
    state_path = root / "state.json"
    original = _live_state()
    state_path.write_text(json.dumps(original))
    monkeypatch.setenv("VARDE_RELAY_PRUNE", "0")

    result = prune_legacy_mailman_state(tmp_path)

    assert result["disabled"] is True
    assert json.loads(state_path.read_text()) == original
    assert list(root.glob("state.json.bak-*")) == []


def test_runner_prunes_once_at_start(tmp_path: Path, monkeypatch) -> None:
    pruned: list[Path] = []

    def prune(working: Path) -> dict[str, int]:
        pruned.append(working)
        return {"pruned": 0}

    monkeypatch.setattr(relay_module, "prune_legacy_mailman_state", prune)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))
    worker = RelayWorker(_stopping_cli(), supervisor=None)

    asyncio.run(worker.run())

    assert pruned == [tmp_path]


def _stopping_cli():
    class StoppingCLI:
        async def status(self) -> dict[str, str]:
            return {"runner_relay": "down"}

        async def bindings(self) -> list[dict]:
            return []

        async def issue_and_bind(self, _session: str) -> str:
            return "token"

        async def issue_and_bind_superseding(self, session: str) -> str:
            return await self.issue_and_bind(session)

        async def wait(self, _identity: str) -> dict:
            raise RelayWaitStopped

        async def confirm(
            self,
            _action: str,
            _result: str,
            _evidence: str,
            _identity: str,
            *,
            harness: str,
        ) -> None:
            pass

        async def renew(self, _action: str) -> dict[str, str]:
            return {"status": "expired"}

        async def end(self, _identity: str) -> None:
            pass

        async def unbind(self, _session: str) -> None:
            pass

    return StoppingCLI()


def test_runner_skips_locked_prune_and_continues_startup(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    def locked_prune(_working: Path) -> dict[str, int]:
        raise Locked("relay state lock timed out")

    monkeypatch.setattr(relay_module, "prune_legacy_mailman_state", locked_prune)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))
    worker = RelayWorker(_stopping_cli(), supervisor=None)

    with caplog.at_level(logging.WARNING):
        asyncio.run(worker.run())

    assert "prune skipped: relay state locked" in caplog.text
    assert worker.state == "stopped"
