"""Bot run state and the governor hook: pause, resume, kill, caps and reservations.

The pure rules live in ``bot_governor``. This module reads the audit log and the
session store, persists ``running | paused | killed`` through the bot repository,
and stops bot-rooted agents. Only user routes and the governor itself call the
state changers; the bot has no route to them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from varde_data.records.bot import AuditRow
from varde_data.repos.bot import BotRepository

from varde_runner.bot_audit import BotAudit
from varde_runner.bot_gateway import Refusal
from varde_runner.bot_governor import (
    Breach,
    Caps,
    Usage,
    bot_rooted,
    budget_warning,
    check_caps,
    count_actions,
    count_launches,
    detect_loop,
    parse_ts,
    reported_tokens,
    session_tokens_today,
)
from varde_runner.bot_profile import BOT_ROLE
from varde_runner.bot_route_policy import Classified, Kind
from varde_runner.bot_tokens import BOT_ACTOR, BotIdentity, BotTokens

logger = logging.getLogger(__name__)

RUN_KEY = "run"
WARNED_KEY = "budget_warned"
GOVERNOR = "system:governor"
STATES = ("running", "paused", "killed")
DEAD = frozenset({"completed", "archived"})
LOOKBACK = timedelta(hours=1)


class ControlError(Exception):
    """A state change the current state does not allow."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class BotControl:
    def __init__(  # noqa: PLR0913 - the control's collaborators, all keyword-only
        self,
        *,
        repo: BotRepository,
        tokens: BotTokens,
        audit: BotAudit,
        supervisor: Callable[[], Awaitable[Any]],
        caps: Callable[[], Caps],
        raise_mailbox: Callable[[str], Awaitable[None]] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repo = repo
        self.tokens = tokens
        self.audit = audit
        self.supervisor = supervisor
        self.caps = caps
        self.raise_mailbox = raise_mailbox
        self.clock = clock
        self._lock = asyncio.Lock()
        self._reserved = 0

    # state ---------------------------------------------------------------

    def run_state(self) -> str:
        state = self.repo.get_state(RUN_KEY)
        return state.state if state is not None else "running"

    async def pause(self, reason: str, by: str, *, stop_agents: bool = False) -> None:
        if self.run_state() != "running":
            return
        self._persist("paused", reason, by)
        await self._interrupt_managers()
        if stop_agents:
            await self.stop_bot_agents()
        self._note(f"Bot paused: {reason}")
        if by.startswith("system:") and self.raise_mailbox is not None:
            await self._raise(reason)

    async def resume(self, by: str) -> None:
        state = self.run_state()
        if state == "killed":
            raise ControlError(409, "bot is killed; start a new generation")
        if state == "running":
            return
        self._persist("running", "resumed", by)
        self._note("Bot resumed")

    async def kill(self, by: str) -> None:
        if self.run_state() == "killed":
            return
        self._persist("killed", "killed by user", by)
        managers = await self._managers()
        for row in managers:
            self.tokens.revoke_session(row["id"])
        await self._stop_ids([row["id"] for row in managers])
        if self.caps().stop_agents_on_stop:
            await self.stop_bot_agents()
        self._note("Bot killed")

    def new_generation(self, by: str) -> None:
        """Leave `killed` for a fresh bot session; only the user's start calls this."""
        if self.run_state() == "killed":
            self._persist("running", "new generation", by)

    async def stop_bot_agents(self) -> list[str]:
        sessions = (await self.supervisor()).store.sessions()
        live = [
            row["id"]
            for row in bot_rooted(sessions)
            if row.get("lifecycle") not in DEAD
        ]
        await self._stop_ids(live)
        return live

    # governor hook ---------------------------------------------------------

    async def governor(
        self, identity: BotIdentity, classified: Classified, body: Mapping[str, Any]
    ) -> Refusal | None:
        """Gateway hook: loop, then caps; reserves a launch slot under the lock."""
        action = classified.route_key
        policy = classified.policy
        if policy is not None and policy.kind == Kind.ALLOW:
            action = "launch" if policy.constraint == "launch" else action
        async with self._lock:
            now = self.clock()
            rows = self._recent_rows(now)
            loop = detect_loop(rows, now)
            if loop is not None:
                await self.pause(loop, GOVERNOR)
                return Refusal(423, loop)
            usage = await self._usage(now)
            breach = check_caps(self.caps(), action, usage, rows, now, self._reserved)
            if breach is not None:
                return await self._refuse(breach)
            await self._warn_budget(usage, now)
            if action == "launch":
                self._reserved += 1
        return None

    def release(self, classified: Classified) -> None:
        """Gateway hook: the launch finished (or failed to start); free its slot."""
        policy = classified.policy
        if policy is not None and policy.constraint == "launch" and self._reserved:
            self._reserved -= 1

    async def _refuse(self, breach: Breach) -> Refusal:
        if breach.pause:
            await self.pause(breach.reason, GOVERNOR, stop_agents=breach.stop_agents)
        return Refusal(breach.status, breach.reason)

    # snapshot --------------------------------------------------------------

    async def snapshot(self) -> dict[str, Any]:
        now = self.clock()
        usage = await self._usage(now)
        rows = self._recent_rows(now)
        caps = self.caps()
        state = self.repo.get_state(RUN_KEY)
        return {
            "state": self.run_state(),
            "reason": state.reason if state else None,
            "changed_at": state.changed_at if state else None,
            "changed_by": state.changed_by if state else None,
            "agents": usage.bot_live,
            "max_concurrent_agents": caps.max_concurrent_agents,
            "launches_last_hour": count_launches(rows, now),
            "max_launches_per_hour": caps.max_launches_per_hour,
            "actions_last_minute": count_actions(rows, now),
            "max_actions_per_minute": caps.max_actions_per_minute,
            "tokens_today": usage.tokens_today,
            "daily_token_budget": caps.daily_token_budget,
        }

    # internals -------------------------------------------------------------

    def _persist(self, state: str, reason: str, by: str) -> None:
        self.repo.set_state(RUN_KEY, state, reason, by)

    def _note(self, summary: str) -> None:
        try:
            row = self.audit.record(
                "call",
                action="control",
                route="bot state",
                args={"summary": summary},
                actor=GOVERNOR,
                status="allowed",
                reason=summary,
            )
            self.audit.post_event(row)
        except Exception:
            logger.exception("could not audit a bot state change")

    async def _raise(self, reason: str) -> None:
        try:
            await self.raise_mailbox(reason)  # type: ignore[misc]
        except Exception:
            logger.exception("could not raise the governor Mailbox item")

    def _recent_rows(self, now: datetime) -> Sequence[AuditRow]:
        since = (now - LOOKBACK).isoformat().replace("+00:00", "Z")
        return self.repo.audit_since(since, BOT_ACTOR)

    async def _usage(self, now: datetime) -> Usage:
        supervisor = await self.supervisor()
        store = supervisor.store
        sessions = store.sessions()
        caps = self.caps()
        rooted = bot_rooted(sessions)
        tokens = sum(
            session_tokens_today(
                parse_ts(row["created_at"]),
                parse_ts(row["updated_at"]) if row.get("lifecycle") in DEAD else None,
                reported_tokens(store.recent_usage_payloads(row["id"])),
                now,
                caps.hourly_token_estimate,
            )
            for row in rooted
        )
        return Usage(
            bot_live=sum(row.get("lifecycle") not in DEAD for row in rooted),
            all_live=sum(row.get("lifecycle") not in DEAD for row in sessions),
            max_live_instances=supervisor.max_live_instances(),
            tokens_today=tokens,
        )

    async def _warn_budget(self, usage: Usage, now: datetime) -> None:
        if not budget_warning(self.caps(), usage):
            return
        today = now.astimezone(UTC).date().isoformat()
        warned = self.repo.get_state(WARNED_KEY)
        if warned is not None and warned.state == today:
            return
        self.repo.set_state(WARNED_KEY, today, "80% of the daily budget", GOVERNOR)
        self._note("Bot has used 80% of its daily token budget")

    async def _managers(self) -> list[dict[str, Any]]:
        sessions = (await self.supervisor()).store.sessions()
        return [
            row
            for row in sessions
            if row.get("role") == BOT_ROLE and row.get("lifecycle") not in DEAD
        ]

    async def _interrupt_managers(self) -> None:
        supervisor = await self.supervisor()
        for row in await self._managers():
            try:
                await supervisor.interrupt(row["id"], GOVERNOR)
            except Exception:
                logger.exception("could not interrupt bot session %s", row["id"])

    async def _stop_ids(self, ids: Sequence[str]) -> None:
        supervisor = await self.supervisor()
        for session_id in ids:
            try:
                await supervisor.stop(session_id, GOVERNOR)
            except Exception:
                logger.exception("could not stop bot-rooted session %s", session_id)
            supervisor.writer_leases.clear(session_id)
