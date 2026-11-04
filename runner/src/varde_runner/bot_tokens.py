"""Bot token registry: token to identity. The caller never supplies identity.

Tokens live in memory only (never in a persisted spec) and are re-issued when
the session is started or resumed again. Only SHA-256 digests are kept.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from collections.abc import Mapping
from dataclasses import dataclass

from varde_runner.bot_profile import BOT_TOKEN_ENV

BOT_ACTOR = "bot:manager"
TOKEN_HEADER = "x-varde-bot-token"  # noqa: S105 - a header name, not a secret


@dataclass(frozen=True, slots=True)
class BotIdentity:
    actor: str
    session_id: str


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class BotTokens:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_digest: dict[str, BotIdentity] = {}

    def issue(self, session_id: str, actor: str = BOT_ACTOR) -> str:
        """Issue a fresh token for a session; its earlier tokens stop working."""
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._drop(session_id)
            self._by_digest[_digest(token)] = BotIdentity(actor, session_id)
        return token

    def descendant_overlay(self, session_id: str) -> Mapping[str, str]:
        """Env overlay for an agent the bot (or a descendant) launched."""
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._drop(session_id)
            self._by_digest[_digest(token)] = BotIdentity(
                f"{BOT_ACTOR}/{session_id}", session_id
            )
        return {BOT_TOKEN_ENV: token}

    def overlay(self, session_id: str) -> Mapping[str, str]:
        """The env overlay a restricted session is launched or resumed with."""
        return {BOT_TOKEN_ENV: self.issue(session_id)}

    def resolve(self, token: str) -> BotIdentity | None:
        with self._lock:
            return self._by_digest.get(_digest(token))

    def revoke_session(self, session_id: str) -> None:
        with self._lock:
            self._drop(session_id)

    def _drop(self, session_id: str) -> None:
        stale = [
            d for d, ident in self._by_digest.items() if ident.session_id == session_id
        ]
        for digest in stale:
            del self._by_digest[digest]
