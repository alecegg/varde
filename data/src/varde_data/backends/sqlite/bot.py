"""SQLite manager-bot audit log and state, in the chat domain's database file."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from varde_core.sqlite import configure_connection
from varde_data.errors import Invalid
from varde_data.records.bot import AuditPhase, AuditRow, BotState

MAX_PAGE = 200
_PHASES = ("call", "result")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _audit(row: sqlite3.Row) -> AuditRow:
    return AuditRow(
        id=row["id"],
        ts=row["ts"],
        phase=row["phase"],
        action=row["action"],
        route=row["route"],
        args_digest=row["args_digest"],
        redacted_args=row["redacted_args"],
        actor=row["actor"],
        status=row["status"],
        reason=row["reason"],
        agent_id=row["agent_id"],
        plan_id=row["plan_id"],
    )


class SqliteBot:
    """Append-only ``bot_audit`` plus ``bot_state``; triggers refuse UPDATE/DELETE."""

    def __init__(self, working_dir: Path, clock: Callable[[], str] = _now) -> None:
        self.path = Path(working_dir) / ".cache" / "dashboard" / "chat.sqlite3"
        self._clock = clock
        self._lock = threading.RLock()
        with self._connection() as db:
            self._migrate(db)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        configure_connection(db)
        try:
            with closing(db), db:
                yield db
        except BaseException:
            db.close()
            raise

    def _migrate(self, db: sqlite3.Connection) -> None:
        # The chat backend owns `PRAGMA user_version` for this file; these tables are
        # additive and idempotent, so they carry no version of their own.
        db.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS bot_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                phase TEXT NOT NULL CHECK(phase IN ('call', 'result')),
                action TEXT NOT NULL,
                route TEXT NOT NULL,
                args_digest TEXT NOT NULL,
                redacted_args TEXT NOT NULL,
                actor TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT,
                agent_id TEXT,
                plan_id TEXT
            );
            CREATE INDEX IF NOT EXISTS bot_audit_ts ON bot_audit(ts);
            CREATE TRIGGER IF NOT EXISTS bot_audit_no_update
                BEFORE UPDATE ON bot_audit
                BEGIN SELECT RAISE(ABORT, 'bot_audit is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS bot_audit_no_delete
                BEFORE DELETE ON bot_audit
                BEGIN SELECT RAISE(ABORT, 'bot_audit is append-only'); END;
            CREATE TABLE IF NOT EXISTS bot_audit_events (
                audit_id INTEGER PRIMARY KEY REFERENCES bot_audit(id),
                message_id TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS bot_audit_events_no_update
                BEFORE UPDATE ON bot_audit_events
                BEGIN SELECT RAISE(ABORT, 'bot_audit_events is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS bot_audit_events_no_delete
                BEFORE DELETE ON bot_audit_events
                BEGIN SELECT RAISE(ABORT, 'bot_audit_events is append-only'); END;
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                reason TEXT,
                changed_at TEXT NOT NULL,
                changed_by TEXT NOT NULL
            );
            COMMIT;
            """
        )

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
    ) -> AuditRow:
        if phase not in _PHASES:
            raise Invalid(f"invalid audit phase: {phase}")
        with self._lock, self._connection() as db:
            cursor = db.execute(
                "INSERT INTO bot_audit(ts, phase, action, route, args_digest,"
                " redacted_args, actor, status, reason, agent_id, plan_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._clock(),
                    phase,
                    action,
                    route,
                    args_digest,
                    redacted_args,
                    actor,
                    status,
                    reason,
                    agent_id,
                    plan_id,
                ),
            )
            row = db.execute(
                "SELECT * FROM bot_audit WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return _audit(row)

    def audit_page(
        self, before: int | None = None, limit: int = 50
    ) -> Sequence[AuditRow]:
        limit = max(1, min(limit, MAX_PAGE))
        with self._lock, self._connection() as db:
            rows = db.execute(
                "SELECT * FROM bot_audit WHERE (? IS NULL OR id < ?)"
                " ORDER BY id DESC LIMIT ?",
                (before, before, limit),
            ).fetchall()
        return [_audit(row) for row in rows]

    def audit_since(
        self, since_ts: str, actor: str | None = None
    ) -> Sequence[AuditRow]:
        with self._lock, self._connection() as db:
            rows = db.execute(
                "SELECT * FROM bot_audit WHERE ts >= ? AND (? IS NULL OR actor = ?"
                " OR substr(actor, 1, length(?) + 1) = ? || '/') ORDER BY id",
                (since_ts, actor, actor, actor or "", actor or ""),
            ).fetchall()
        return [_audit(row) for row in rows]

    def unevented_audit(self, limit: int = 50) -> Sequence[AuditRow]:
        with self._lock, self._connection() as db:
            rows = db.execute(
                "SELECT a.* FROM bot_audit a LEFT JOIN bot_audit_events e"
                " ON e.audit_id = a.id WHERE e.audit_id IS NULL"
                " AND a.phase = 'call' AND a.status != 'read'"
                " AND NOT (a.action = 'permission' AND a.status = 'allowed')"
                " ORDER BY a.id LIMIT ?",
                (limit,),
            ).fetchall()
        return [_audit(row) for row in rows]

    def mark_evented(self, audit_id: int, message_id: str) -> bool:
        with self._lock, self._connection() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO bot_audit_events(audit_id, message_id)"
                " VALUES (?, ?)",
                (audit_id, message_id),
            )
            return cursor.rowcount == 1

    def get_state(self, key: str) -> BotState | None:
        with self._lock, self._connection() as db:
            row = db.execute("SELECT * FROM bot_state WHERE key = ?", (key,)).fetchone()
        return BotState(**dict(row)) if row else None

    def set_state(
        self, key: str, state: str, reason: str | None, changed_by: str
    ) -> BotState:
        with self._lock, self._connection() as db:
            db.execute(
                "INSERT INTO bot_state(key, state, reason, changed_at, changed_by)"
                " VALUES (?, ?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET"
                " state = excluded.state, reason = excluded.reason,"
                " changed_at = excluded.changed_at, changed_by = excluded.changed_by",
                (key, state, reason, self._clock(), changed_by),
            )
            row = db.execute("SELECT * FROM bot_state WHERE key = ?", (key,)).fetchone()
        return BotState(**dict(row))
