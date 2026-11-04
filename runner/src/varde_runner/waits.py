"""Pure helpers for durable wait ids and expiry decisions."""

from datetime import UTC, datetime


def approval_wait_id(session_id: str, request_id: str) -> str:
    return f"approval:{session_id}:{request_id}"


def is_expired(deadline: str | None, *, now: datetime | None = None) -> bool:
    if deadline is None:
        return False
    current = now or datetime.now(UTC)
    return datetime.fromisoformat(deadline) <= current


def response_for_wait(stored_decision: str | None, requested_decision: str) -> str:
    if stored_decision is None:
        return "stale"
    stored = normalize_decision(stored_decision)
    requested = normalize_decision(requested_decision)
    return "responded" if stored is not None and stored == requested else "stale"


def normalize_decision(decision: object) -> str | None:
    if not isinstance(decision, str):
        return None
    normalized = decision.strip().lower().replace("-", "_")
    return {
        "approve": "approve",
        "approved": "approve",
        "allow": "approve",
        "allowed": "approve",
        "deny": "deny",
        "denied": "deny",
        "reject": "deny",
        "rejected": "deny",
        "ask_more": "ask_more",
        "expired": "expired",
    }.get(normalized)
