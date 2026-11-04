"""Manager bot generation start, wake threshold, and safe replacement."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_data.repos.chat import ChatRepository
from varde_workflow.handoff_format import validate

from varde_runner.bot_prompt import MANAGER_BOT_PROMPT, replacement_prompt

logger = logging.getLogger(__name__)

CONTEXT_REPLACEMENT_TOKENS = 200_000
THREAD_TAIL_MESSAGES = 30
LIFECYCLE_POLL_SECONDS = 30


@dataclass(frozen=True)
class LifecycleHooks:
    get_supervisor: Callable[[], Awaitable[Any]]
    launch: Callable[[str], Awaitable[str]]
    run_state: Callable[[], str]
    commit_notes: Callable[[Path], Awaitable[None]]


def context_tokens(store: Any, session_id: str) -> int | None:
    """Read the latest context usage reported for one runner session."""
    payloads = store.recent_usage_payloads(session_id, 1)
    if not payloads:
        return None
    value = payloads[0].get("context_tokens")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def latest_handoff(notes_path: Path) -> str | None:
    """Extract and validate the newest handoff section from manager notes."""
    try:
        text = notes_path.read_text(encoding="utf-8")
    except OSError:
        return None
    start = text.rfind("Summary:")
    if start < 0 or (start and text[start - 1] not in "\r\n"):
        return None
    handoff = text[start:].strip()
    result = validate(handoff, lambda item: Path(item).exists())
    return handoff if not result.errors else None


class ManagerBotLifecycle:
    """Coordinate one restricted manager session and its replacement generations."""

    def __init__(
        self,
        *,
        chat: ChatRepository,
        working_dir: Path,
        hooks: LifecycleHooks,
        poll_seconds: float = LIFECYCLE_POLL_SECONDS,
    ) -> None:
        self.chat = chat
        self.working_dir = working_dir
        self.hooks = hooks
        self.poll_seconds = poll_seconds
        self._stopped = asyncio.Event()
        self._start_lock = asyncio.Lock()

    async def start(self) -> str:
        """Start a generation if none is live, returning its managed agent id."""
        async with self._start_lock:
            return await self._start_locked()

    async def _start_locked(self) -> str:
        if self.hooks.run_state() != "running":
            raise RuntimeError(f"manager bot is {self.hooks.run_state()}")
        current = self.chat.get_chat_bot("main")
        supervisor = await self.hooks.get_supervisor()
        if current is not None:
            row = supervisor.resolve_session(current.agent_id)
            if row is not None and row.get("lifecycle") not in {
                "completed",
                "archived",
            }:
                return current.agent_id
        generation = current.generation + 1 if current is not None else 1
        agent_id = await self.hooks.launch(_initial_prompt())
        self.chat.set_chat_bot("main", agent_id, _now(), None, "running", generation)
        return agent_id

    async def run(self) -> None:
        """Replace after an idle turn has a valid handoff."""
        self._stopped.clear()
        while not self._stopped.is_set():
            try:
                await self.replace_if_due()
            except Exception:
                logger.exception("manager bot lifecycle check failed")
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stopped.wait(), self.poll_seconds)

    def stop(self) -> None:
        self._stopped.set()

    async def replace_if_due(self) -> bool:
        if self.hooks.run_state() != "running":
            return False
        current = self.chat.get_chat_bot("main")
        if current is None:
            return False
        supervisor = await self.hooks.get_supervisor()
        tokens = context_tokens(supervisor.store, current.agent_id)
        if tokens is None or tokens < CONTEXT_REPLACEMENT_TOKENS:
            return False
        status = await supervisor.target_idle_status(current.agent_id)
        if status != "idle":
            return False
        notes_path = self.working_dir / "session-notes" / "manager-bot" / "notes.md"
        handoff = latest_handoff(notes_path)
        if handoff is None:
            logger.warning(
                "manager bot reached replacement threshold without a valid handoff"
            )
            return False
        await self.hooks.commit_notes(notes_path)
        tail = self.chat.page("main", limit=THREAD_TAIL_MESSAGES)
        prompt = replacement_prompt(
            handoff,
            [(item.role, item.text) for item in tail],
        )
        await supervisor.stop(current.agent_id, "system:manager-lifecycle")
        agent_id = await self.hooks.launch(prompt)
        self.chat.set_chat_bot(
            "main", agent_id, _now(), None, "running", current.generation + 1
        )
        self.chat.append_event(
            "event",
            f"Manager bot generation {current.generation + 1} started",
            f"/thread/{agent_id}",
            "main",
        )
        return True


def _initial_prompt() -> str:
    return MANAGER_BOT_PROMPT


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
