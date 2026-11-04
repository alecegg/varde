"""Backend-neutral manager-bot audit and state API.

The audit side is append-only by construction: the protocol has no update or
delete method. State rows change only through ``set_state``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from varde_data.records.bot import AuditPhase, AuditRow, BotState


class BotRepository(Protocol):
    def append_audit(  # noqa: PLR0913, PLR0917 - one flat audit record
        self,
        phase: AuditPhase,
        action: str,
        route: str,
        args_digest: str,
        redacted_args: str,
        actor: str,
        status: str,
        reason: str | None = None,
        agent_id: str | None = None,
        plan_id: str | None = None,
    ) -> AuditRow: ...

    def audit_page(
        self, before: int | None = None, limit: int = 50
    ) -> Sequence[AuditRow]: ...

    def audit_since(
        self, since_ts: str, actor: str | None = None
    ) -> Sequence[AuditRow]: ...

    def unevented_audit(self, limit: int = 50) -> Sequence[AuditRow]: ...

    def mark_evented(self, audit_id: int, message_id: str) -> bool: ...

    def get_state(self, key: str) -> BotState | None: ...

    def set_state(
        self, key: str, state: str, reason: str | None, changed_by: str
    ) -> BotState: ...


__all__ = ["BotRepository"]
