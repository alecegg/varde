"""Bot audit service: redacted, digested, append-only records plus chat event rows."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from typing import Any

from varde_data.records.bot import AuditPhase, AuditRow
from varde_data.repos.bot import BotRepository
from varde_data.repos.chat import ChatRepository

logger = logging.getLogger(__name__)

FREE_TEXT_KEYS = frozenset({"prompt", "text", "body", "content", "message"})
MAX_REDACTED_CHARS = 500
EVENT_KIND = "bot"
RETRY_SECONDS = 5.0


def digest_args(args: Mapping[str, Any]) -> str:
    canonical = json.dumps(args, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def redact_args(args: Mapping[str, Any]) -> str:
    """Keep structure and short fields; free text becomes a length marker."""
    kept = {
        key: f"[{len(value)} chars]"
        if key in FREE_TEXT_KEYS and isinstance(value, str)
        else value
        for key, value in args.items()
    }
    text = json.dumps(kept, sort_keys=True, default=str, separators=(",", ":"))
    return (
        text if len(text) <= MAX_REDACTED_CHARS else text[:MAX_REDACTED_CHARS] + "..."
    )


def event_summary(row: AuditRow) -> str:
    verb = "Refused" if row.status == "denied" else "Bot"
    suffix = f" ({row.reason})" if row.reason else ""
    return f"{verb}: {row.action}{suffix}"


def event_link(row: AuditRow) -> str | None:
    if row.agent_id:
        return f"/thread/{row.agent_id}"
    if row.plan_id:
        return f"/plans/{row.plan_id}"
    return None


class BotAudit:
    def __init__(
        self,
        repo: BotRepository,
        chat: ChatRepository | None = None,
        retry_seconds: float = RETRY_SECONDS,
    ) -> None:
        self.repo = repo
        self.chat = chat
        self.retry_seconds = retry_seconds
        self._retry_pending = False

    def record(  # noqa: PLR0913 - one flat audit record
        self,
        phase: AuditPhase,
        *,
        action: str,
        route: str,
        args: Mapping[str, Any],
        actor: str,
        status: str,
        reason: str | None = None,
        agent_id: str | None = None,
        plan_id: str | None = None,
    ) -> AuditRow:
        return self.repo.append_audit(
            phase,
            action,
            route,
            digest_args(args),
            redact_args(args),
            actor,
            status,
            reason,
            agent_id,
            plan_id,
        )

    def post_event(self, row: AuditRow) -> bool:
        """Write the `main` event row for an audit row; False means retry later."""
        if self.chat is None:
            return True
        try:
            message = self.chat.append_event(
                EVENT_KIND, event_summary(row), event_link(row)
            )
            self.repo.mark_evented(row.id, message.id)
        except Exception:
            logger.exception("could not post bot event for audit row %s", row.id)
            self._schedule_retry()
            return False
        return True

    def _schedule_retry(self) -> None:
        """Retry unevented rows on the running loop until each has its event."""
        if self._retry_pending:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._retry_pending = True
        loop.call_later(self.retry_seconds, self._retry_tick)

    def start_retries(self) -> None:
        """Post events a crash or chat outage left unposted (call once at startup)."""
        self._retry_tick()

    def _retry_tick(self) -> None:
        self._retry_pending = False
        try:
            self.retry_events()
        except Exception:
            logger.exception("bot event retry failed")
            self._schedule_retry()

    def retry_events(self, limit: int = 50) -> int:
        """Post event rows for audit rows that have none; returns the count posted."""
        return sum(self.post_event(row) for row in self.repo.unevented_audit(limit))
