from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from varde_data.config import DataConfig
from varde_data.errors import Conflict, Invalid, Locked, WrongMode
from varde_data.open import open_data
from varde_data.queue import open_queue
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItemInput
from varde_data.repos.queue import QueueRepository
from varde_runner import lease_keeper
from varde_runner.lease_keeper import expire_tick


def test_expiry_loop_survives_transient_store_error(monkeypatch) -> None:
    class FailsOnce:
        calls = 0

        def expire(self, now: str) -> list[object]:
            self.calls += 1
            if self.calls == 1:
                raise OSError("temporary store failure")
            return []

    repo = FailsOnce()
    sleeps = 0

    async def stop_after_success(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if repo.calls == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(lease_keeper.asyncio, "sleep", stop_after_success)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            lease_keeper.run_expiry_ticks(lambda: cast("QueueRepository", repo))
        )

    assert repo.calls == 2
    assert sleeps == 2


def test_expiry_loop_tolerates_wrong_mode_until_store_setup(
    monkeypatch, caplog
) -> None:
    caplog.set_level(logging.DEBUG)

    class WrongModeRepo:
        def expire(self, now: str) -> list[object]:
            raise WrongMode("queue store is not in sqlite mode")

    async def stop_after_tick(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(lease_keeper.asyncio, "sleep", stop_after_tick)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            lease_keeper.run_expiry_ticks(
                lambda: cast("QueueRepository", WrongModeRepo())
            )
        )

    assert "queue lease expiry unavailable before SQLite store setup" in caplog.text


@pytest.mark.parametrize(
    ("failure", "expected_delays"),
    [(Invalid("migration pending"), [60, 15]), (Locked("busy"), [15, 15])],
)
def test_expiry_loop_retries_unavailable_queue(
    monkeypatch, failure: Exception, expected_delays: list[int]
) -> None:
    class Repo:
        calls = 0

        def expire(self, now: str) -> list[object]:
            self.calls += 1
            return []

    repo = Repo()
    getter_calls = 0
    delays: list[int] = []

    def get_repo() -> QueueRepository:
        nonlocal getter_calls
        getter_calls += 1
        if getter_calls == 1:
            raise failure
        return cast("QueueRepository", repo)

    async def stop_after_recovery(seconds: float) -> None:
        delays.append(int(seconds))
        if repo.calls == 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(lease_keeper.asyncio, "sleep", stop_after_recovery)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(lease_keeper.run_expiry_ticks(get_repo))

    assert repo.calls == 1
    assert delays == expected_delays


def test_expire_tick_requeues_lapsed_claim_and_keeps_renewed_claim() -> None:
    repo = open_queue(Path.cwd(), "memory")
    now = datetime.now(UTC)
    stamp = now.isoformat()
    for item_id in ("lapsed", "renewed"):
        repo.enqueue(QueueItemInput(item_id, "plan", queue_name="roles/plan"))
    lapsed = repo.claim("roles/plan", worker="slot-a", lease_s=10, now=stamp)
    renewed = repo.claim("roles/plan", worker="slot-b", lease_s=10, now=stamp)
    assert lapsed and renewed
    repo.renew(
        "roles/plan",
        renewed.id,
        worker="slot-b",
        generation=renewed.claim_generation,
        lease_s=120,
    )

    expired = expire_tick(repo, now + timedelta(seconds=30))

    assert expired == 1
    lapsed_after = repo.get("roles/plan", lapsed.id)
    renewed_after = repo.get("roles/plan", renewed.id)
    assert lapsed_after.state == "queued"
    assert lapsed_after.claim_generation == lapsed.claim_generation + 1
    assert renewed_after.state == "claimed"


def test_stale_slot_epoch_cannot_renew_claim(tmp_path: Path) -> None:
    initialize(tmp_path)
    database = tmp_path / QUEUE_DATABASE
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'"
        )
    data = open_data(tmp_path, DataConfig())
    data.slots.register(
        "slot-a", plan_id="plan", role="builder", agent_ref="agent", lease_s=30
    )
    data.queue.enqueue(QueueItemInput("item", "plan", queue_name="roles/plan"))
    claim = data.slots.claim(
        "slot-a",
        epoch=1,
        queue_name="roles/plan",
        lease_s=30,
        now="2030-01-01T00:00:00+00:00",
    )
    assert claim is not None
    data.slots.replace(
        "slot-a",
        new_agent_ref="replacement",
        lease_s=60,
        now="2030-01-01T00:00:05+00:00",
    )

    with pytest.raises(Conflict):
        data.slots.heartbeat(
            "slot-a", epoch=1, lease_s=60, now="2030-01-01T00:00:10+00:00"
        )
