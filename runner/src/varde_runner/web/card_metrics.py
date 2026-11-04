"""Record decision-card metrics on the Supervisor's event loop."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from varde_runner.decision_metrics import card_kind_for, response_for_answer

logger = logging.getLogger(__name__)


class CardMetricsRecorder:
    def __init__(self, get_supervisor: Callable[[], Awaitable[Any]]) -> None:
        self.get_supervisor = get_supervisor
        self.lock = threading.Lock()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.pending: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, event: str, decision: dict[str, Any]) -> None:
        if decision.get("kind") == "permission":
            return
        with self.lock:
            if self.loop is None:
                self.pending.append((event, decision.copy()))
                return
            self.loop.call_soon_threadsafe(self._schedule, event, decision.copy())

    def bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        with self.lock:
            self.loop = loop
            for event, decision in self.pending:
                self._schedule(event, decision)
            self.pending.clear()

    def _schedule(self, event: str, decision: dict[str, Any]) -> None:
        asyncio.create_task(self._persist(event, decision))

    async def _persist(self, event: str, decision: dict[str, Any]) -> None:
        try:
            supervisor = await self.get_supervisor()
            request_id = decision.get("decision_id")
            if not isinstance(request_id, str) or not request_id:
                return
            if event == "created":
                supervisor.store.record_decision_event(
                    request_id,
                    plan=decision.get("plan_id"),
                    card_kind=card_kind_for(decision),
                )
                return
            response = response_for_answer(str(decision.get("answer", "")), decision)
            if response is not None:
                supervisor.store.answer_decision_event(request_id, response)
        except Exception:
            logger.exception("Could not persist decision metric event %s", event)
