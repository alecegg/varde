"""SQLite-backed session projection and append-only event history."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_runner.guard_log import redact_prompt
from varde_runner.liveness import (
    AGENT_OUTPUT_KINDS,
    AGENT_OUTPUT_SESSION_END_STATUSES,
)

LIFECYCLES = {
    "starting",
    "idle",
    "running",
    "awaiting_permission",
    "awaiting_question",
    "rate_limited",
    "interrupted",
    "completed",
    "failed",
    "archived",
}
DECISION_FIELDS = {
    "plan",
    "role",
    "harness",
    "model",
    "harness_mode",
    "card_kind",
    "request_kind",
    "request_key",
    "response",
    "approved_before",
}
DECISION_RESPONSES = {"approve", "deny", "ask_more", "expired"}
logger = logging.getLogger(__name__)


def _lifecycle_for_status(status: str) -> str:
    return {"running": "running", "error": "failed", "completed": "completed"}.get(
        status, "idle"
    )


def _agent_output_filter() -> tuple[str, tuple[str, ...]]:
    """Return the SQL clause and parameters matching agent-output events."""
    kinds = tuple(sorted(AGENT_OUTPUT_KINDS))
    statuses = tuple(sorted(AGENT_OUTPUT_SESSION_END_STATUSES))
    sql = (
        f"(kind IN ({', '.join('?' for _ in kinds)}) "
        "OR (kind = 'session_end' AND json_extract(payload, '$.status') "
        f"IN ({', '.join('?' for _ in statuses)})))"
    )
    return sql, (*kinds, *statuses)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SessionStore:
    def __init__(self, data_dir: Path) -> None:
        self.on_commit: Callable[[str], None] | None = None
        data_dir.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(data_dir / "runner.sqlite3")
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self._migrate()
        except Exception:
            self.connection.close()
            raise

    def _migrate(self) -> None:  # noqa: PLR0915 - ordered schema migrations
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > 7:
            raise RuntimeError(f"unsupported store schema version: {version}")
        if version == 0:
            self.connection.execute("BEGIN")
            try:
                self.connection.execute(
                    """CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, backend TEXT NOT NULL, ref TEXT NOT NULL,
                    role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'unknown',
                    idle_status TEXT NOT NULL DEFAULT 'unknown', """
                    """last_event_seq INTEGER NOT NULL DEFAULT 0)"""
                )
                self.connection.execute(
                    """CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    kind TEXT NOT NULL, payload TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id))"""
                )
                self.connection.execute("PRAGMA user_version = 1")
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            version = 1
        if version < 2:
            self.connection.execute("BEGIN")
            try:
                self._migrate_to_v2()
                self.connection.execute("PRAGMA user_version = 2")
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            version = 2
        if version < 3:
            self.connection.execute("BEGIN")
            try:
                self._migrate_to_v3()
                self.connection.execute("PRAGMA user_version = 3")
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            version = 3
        if version < 4:
            self.connection.execute("BEGIN")
            try:
                self._migrate_to_v4()
                self.connection.execute("PRAGMA user_version = 4")
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            version = 4
        if version < 5:
            self.connection.execute("BEGIN")
            try:
                self._migrate_to_v5()
                self.connection.execute("PRAGMA user_version = 5")
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            version = 5
        if version < 6:
            self.connection.execute("BEGIN")
            try:
                self._migrate_to_v6()
                self.connection.execute("PRAGMA user_version = 6")
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            version = 6
        if version < 7:
            self.connection.execute("BEGIN")
            try:
                self._migrate_to_v7()
                self.connection.execute("PRAGMA user_version = 7")
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            version = 7

        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS session_address_bindings (
            session_id TEXT PRIMARY KEY, working_dir TEXT NOT NULL,
            remote_session_id TEXT NOT NULL)"""
        )
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._ensure_wake_message_index()
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS send_admissions (
            session_id TEXT NOT NULL, request_id TEXT NOT NULL,
            outcome TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(session_id, request_id))"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS job_schedules (
            job_key TEXT PRIMARY KEY, enabled INTEGER NOT NULL,
            schedule_time TEXT NOT NULL, updated_at TEXT NOT NULL)"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS job_runs (
            id INTEGER PRIMARY KEY, job_key TEXT NOT NULL,
            started_at TEXT NOT NULL, finished_at TEXT, trigger TEXT NOT NULL,
            outcome TEXT NOT NULL, error TEXT, model_tokens INTEGER,
            cost_usd REAL)"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS job_runs_job_id_idx "
            "ON job_runs(job_key, id DESC)"
        )
        event_columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(events)")
        }
        if "created_at" not in event_columns:
            self.connection.execute("ALTER TABLE events ADD COLUMN created_at TEXT")
            self.connection.execute(
                "UPDATE events SET created_at = ? WHERE created_at IS NULL", (_now(),)
            )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS events_session_seq ON events(session_id, seq)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS events_session_created_at "
            "ON events(session_id, created_at)"
        )
        self.connection.commit()
        self.prune_send_admissions()

    def change_count(self) -> int:
        """Return the number of writes made through this store connection."""
        return self.connection.total_changes

    def get_send_admission(self, session_id: str, request_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT outcome FROM send_admissions "
            "WHERE session_id = ? AND request_id = ?",
            (session_id, request_id),
        ).fetchone()
        return None if row is None else str(row["outcome"])

    def set_address_binding(
        self, session_id: str, working_dir: str, remote_id: str
    ) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO session_address_bindings VALUES (?, ?, ?)",
            (session_id, working_dir, remote_id),
        )
        self.connection.commit()

    def get_address_binding(self, session_id: str) -> dict[str, str] | None:
        row = self.connection.execute(
            "SELECT working_dir, remote_session_id FROM session_address_bindings "
            "WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "working_dir": row["working_dir"],
            "remote_session_id": row["remote_session_id"],
        }

    def delete_address_binding(self, session_id: str) -> None:
        self.connection.execute(
            "DELETE FROM session_address_bindings WHERE session_id = ?", (session_id,)
        )
        self.connection.commit()

    def record_send_admission(
        self, session_id: str, request_id: str, outcome: str
    ) -> None:
        self._prune_old_send_admissions()
        self.connection.execute(
            "INSERT OR IGNORE INTO send_admissions "
            "(session_id, request_id, outcome, created_at) VALUES (?, ?, ?, ?)",
            (session_id, request_id, outcome, _now()),
        )
        self.connection.commit()

    def prune_send_admissions(self) -> None:
        self._prune_old_send_admissions()
        self.connection.commit()

    def _prune_old_send_admissions(self) -> None:
        cutoff = datetime.fromtimestamp(
            datetime.now(UTC).timestamp() - 7 * 24 * 60 * 60, UTC
        ).isoformat()
        self.connection.execute(
            "DELETE FROM send_admissions WHERE created_at < ?", (cutoff,)
        )

    def _migrate_to_v7(self) -> None:
        existing = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(sessions)")
        }
        if "launched_by" not in existing:
            self.connection.execute("ALTER TABLE sessions ADD COLUMN launched_by TEXT")

    def _migrate_to_v6(self) -> None:
        existing = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(sessions)")
        }
        if "parent_id" not in existing:
            self.connection.execute("ALTER TABLE sessions ADD COLUMN parent_id TEXT")

    def _migrate_to_v5(self) -> None:
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS guard_verdicts (
            id INTEGER PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT NOT NULL,
            request_id TEXT NOT NULL, request_key TEXT NOT NULL,
            request_kind TEXT NOT NULL, prompt TEXT NOT NULL, verdict TEXT NOT NULL,
            reason TEXT NOT NULL, escalated INTEGER NOT NULL,
            UNIQUE(session_id, request_id))"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS guard_verdicts_request_key_idx "
            "ON guard_verdicts(request_key)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS guard_revocations "
            "(request_key TEXT PRIMARY KEY, ts TEXT NOT NULL)"
        )

    def _migrate_to_v4(self) -> None:
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS waits (
            wait_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('approval', 'wake')),
            state TEXT NOT NULL CHECK(
                state IN ('pending', 'resolved', 'expired', 'cancelled')
            ),
            deadline TEXT, payload TEXT NOT NULL, decision TEXT,
            created_at TEXT NOT NULL, resolved_at TEXT)"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS waits_state_deadline ON waits(state, deadline)"
        )

    def _ensure_wake_message_index(self) -> None:
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS wake_message_ids "
            "(wait_id TEXT NOT NULL, message_id TEXT NOT NULL, "
            "PRIMARY KEY(wait_id, message_id))"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS wake_message_id_lookup "
            "ON wake_message_ids(message_id, wait_id)"
        )
        for row in self.connection.execute(
            "SELECT wait_id, payload FROM waits WHERE kind = 'wake'"
        ):
            self._index_wake_message_ids(row["wait_id"], json.loads(row["payload"]))
        self.connection.commit()

    def _index_wake_message_ids(self, wait_id: str, payload: dict[str, Any]) -> None:
        self.connection.executemany(
            "INSERT OR IGNORE INTO wake_message_ids(wait_id, message_id) VALUES (?, ?)",
            [
                (wait_id, message_id)
                for message_id in payload.get("message_ids", [])
                if isinstance(message_id, str)
            ],
        )

    def _migrate_to_v3(self) -> None:
        existing = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(sessions)")
        }
        for name in ("no_progress_restarts", "seq_at_last_start"):
            if name not in existing:
                self.connection.execute(
                    f"ALTER TABLE sessions ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0"
                )

    def _migrate_to_v2(self) -> None:
        columns = (
            ("harness", "TEXT"),
            ("agent_id", "TEXT"),
            ("workspace_id", "TEXT"),
            ("model", "TEXT"),
            ("reasoning_effort", "TEXT"),
            ("mode", "TEXT"),
            ("lifecycle", "TEXT NOT NULL DEFAULT 'idle'"),
            ("capabilities", "TEXT NOT NULL DEFAULT '{}'"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        )
        existing = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(sessions)")
        }
        for name, declaration in columns:
            if name not in existing:
                self.connection.execute(
                    f"ALTER TABLE sessions ADD COLUMN {name} {declaration}"
                )
        self.connection.execute(
            "UPDATE sessions SET agent_id = id WHERE agent_id IS NULL"
        )
        self.connection.execute(
            "UPDATE sessions SET harness = backend WHERE harness IS NULL"
        )
        self.connection.execute(
            "UPDATE sessions SET lifecycle = CASE status "
            "WHEN 'running' THEN 'running' WHEN 'error' THEN 'failed' "
            "WHEN 'completed' THEN 'completed' ELSE 'idle' END "
            "WHERE lifecycle IS NULL OR lifecycle = 'idle'"
        )
        now = _now()
        self.connection.execute(
            "UPDATE sessions SET created_at = ? WHERE created_at IS NULL", (now,)
        )
        self.connection.execute(
            "UPDATE sessions SET updated_at = ? WHERE updated_at IS NULL", (now,)
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY, repo_root TEXT NOT NULL, cwd TEXT NOT NULL,
            worktree TEXT, branch TEXT, created_at TEXT NOT NULL, archived_at TEXT)"""
        )
        event_columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(events)")
        }
        if "created_at" not in event_columns:
            self.connection.execute("ALTER TABLE events ADD COLUMN created_at TEXT")
        self.connection.execute(
            "UPDATE events SET created_at = ? WHERE created_at IS NULL", (now,)
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS decision_event (
            request_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, answered_at TEXT,
            time_to_answer_s REAL, plan TEXT, role TEXT, harness TEXT, model TEXT,
            harness_mode TEXT, card_kind TEXT, request_kind TEXT, request_key TEXT,
            response TEXT, approved_before INTEGER)"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS decision_event_request_key_idx "
            "ON decision_event(request_key)"
        )

    def create_session(  # noqa: PLR0913
        self,
        session_id: str,
        backend: str,
        ref: dict[str, Any],
        role: str,
        *,
        harness: str | None = None,
        agent_id: str | None = None,
        workspace_id: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        mode: str | None = None,
        lifecycle: str = "idle",
        capabilities: dict[str, Any] | None = None,
    ) -> None:
        self._validate_lifecycle(lifecycle)
        now = _now()
        self.connection.execute(
            """INSERT INTO sessions
            (id, backend, ref, role, harness, agent_id, workspace_id, model,
             reasoning_effort, mode, lifecycle, capabilities, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                backend,
                json.dumps(ref),
                role,
                harness or backend,
                agent_id or session_id,
                workspace_id,
                model,
                reasoning_effort,
                mode,
                lifecycle,
                json.dumps(capabilities or {}),
                now,
                now,
            ),
        )
        self.connection.commit()

    @staticmethod
    def _validate_lifecycle(value: Any) -> None:
        if value not in LIFECYCLES:
            raise ValueError("invalid lifecycle")

    def update_session(self, session_id: str, **values: str | int) -> None:
        allowed = {
            "status",
            "idle_status",
            "last_event_seq",
            "no_progress_restarts",
            "seq_at_last_start",
            "harness",
            "agent_id",
            "workspace_id",
            "model",
            "reasoning_effort",
            "mode",
            "lifecycle",
            "capabilities",
            "parent_id",
            "launched_by",
            "updated_at",
        }
        if not values or values.keys() - allowed:
            raise ValueError("invalid session fields")
        if "lifecycle" in values:
            self._validate_lifecycle(values["lifecycle"])
            current = self.get_session(session_id)
            if (
                current
                and current["lifecycle"] == "archived"
                and values["lifecycle"] != "archived"
            ):
                raise ValueError("archived lifecycle is terminal")
        elif "status" in values:
            current = self.get_session(session_id)
            if current and current["lifecycle"] != "archived":
                values["lifecycle"] = _lifecycle_for_status(str(values["status"]))
        if "capabilities" in values and not isinstance(values["capabilities"], str):
            values["capabilities"] = json.dumps(values["capabilities"])
        values.setdefault("updated_at", _now())
        assignments = ", ".join(f"{key} = ?" for key in values)
        self.connection.execute(
            f"UPDATE sessions SET {assignments} WHERE id = ?",  # noqa: S608 - Assignment names come from the fixed values mapping.
            (*values.values(), session_id),
        )
        self.connection.commit()

    def upsert_workspace(
        self,
        workspace_id: str,
        *,
        repo_root: str,
        cwd: str,
        worktree: str | None = None,
        branch: str | None = None,
        archived_at: str | None = None,
    ) -> None:
        self.connection.execute(
            """INSERT INTO workspaces(
            id, repo_root, cwd, worktree, branch, created_at, archived_at)
            VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET
            repo_root=excluded.repo_root, cwd=excluded.cwd,
            worktree=COALESCE(excluded.worktree, workspaces.worktree),
            branch=COALESCE(excluded.branch, workspaces.branch),
            archived_at=COALESCE(excluded.archived_at, workspaces.archived_at)""",
            (workspace_id, repo_root, cwd, worktree, branch, _now(), archived_at),
        )
        self.connection.commit()

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
        return dict(row) if row else None

    def record_decision_event(self, request_id: str, **values: Any) -> bool:
        if values.keys() - DECISION_FIELDS:
            raise ValueError("invalid decision event fields")
        response = values.get("response")
        if response is not None and response not in DECISION_RESPONSES:
            raise ValueError("invalid decision response")
        fields = {"request_id": request_id, "created_at": _now(), **values}
        names = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        self.connection.execute(
            f"INSERT INTO decision_event ({names}) VALUES ({marks}) "  # noqa: S608 - identifiers are constrained by DECISION_FIELDS
            "ON CONFLICT(request_id) DO NOTHING",
            tuple(fields.values()),
        )
        self.connection.commit()
        return self.connection.execute("SELECT changes()").fetchone()[0] == 1

    def has_decision_event(self, request_id: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM decision_event WHERE request_id = ? LIMIT 1",
                (request_id,),
            ).fetchone()
            is not None
        )

    def approved_before(self, request_key: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM decision_event WHERE request_key = ? "
                "AND response = 'approve' LIMIT 1",
                (request_key,),
            ).fetchone()
            is not None
        )

    def record_guard_verdict(  # noqa: PLR0913, PLR0917 - complete audit record
        self,
        session_id: str,
        request_id: str,
        request_key: str,
        request_kind: str,
        prompt: str,
        verdict: str,
        reason: str,
        escalated: bool,
    ) -> bool:
        if verdict not in {"approve", "escalate"}:
            raise ValueError("invalid guard verdict")
        cursor = self.connection.execute(
            "INSERT INTO guard_verdicts "
            "(ts, session_id, request_id, request_key, request_kind, prompt, "
            "verdict, reason, escalated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id, request_id) DO NOTHING",
            (
                _now(),
                session_id,
                request_id,
                request_key,
                request_kind,
                redact_prompt(prompt),
                verdict,
                redact_prompt(reason),
                int(escalated),
            ),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def guard_verdicts(
        self, limit: int, before_id: int | None = None
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        if before_id is None:
            rows = self.connection.execute(
                "SELECT * FROM guard_verdicts ORDER BY id DESC LIMIT ?", (limit,)
            )
        else:
            rows = self.connection.execute(
                "SELECT * FROM guard_verdicts WHERE id < ? ORDER BY id DESC LIMIT ?",
                (before_id, limit),
            )
        return [dict(row) for row in rows]

    def revoke_guard_pattern(self, key: str) -> None:
        self.connection.execute(
            "INSERT INTO guard_revocations(request_key, ts) VALUES (?, ?) "
            "ON CONFLICT(request_key) DO UPDATE SET ts = excluded.ts",
            (key, _now()),
        )
        self.connection.commit()

    def unrevoke_guard_pattern(self, key: str) -> None:
        self.connection.execute(
            "DELETE FROM guard_revocations WHERE request_key = ?", (key,)
        )
        self.connection.commit()

    def revoked_guard_patterns(self) -> frozenset[str]:
        return frozenset(
            row[0]
            for row in self.connection.execute(
                "SELECT request_key FROM guard_revocations"
            )
        )

    def guard_verdict_for(
        self, session_id: str, request_id: str
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM guard_verdicts WHERE session_id = ? AND request_id = ?",
            (session_id, request_id),
        ).fetchone()
        return dict(row) if row else None

    def decision_events(self, since: str | None = None) -> list[dict[str, Any]]:
        if since is None:
            rows = self.connection.execute(
                "SELECT * FROM decision_event ORDER BY created_at, request_id"
            )
        else:
            rows = self.connection.execute(
                "SELECT * FROM decision_event WHERE created_at >= ? "
                "ORDER BY created_at, request_id",
                (since,),
            )
        return [dict(row) for row in rows]

    def answer_decision_event(self, request_id: str, response: str) -> bool:
        if response not in DECISION_RESPONSES:
            raise ValueError("invalid decision response")
        answered = _now()
        self.connection.execute(
            "UPDATE decision_event SET answered_at = ?, time_to_answer_s = "
            "(julianday(?) - julianday(created_at)) * 86400, response = ? "
            "WHERE request_id = ? AND answered_at IS NULL",
            (answered, answered, response, request_id),
        )
        self.connection.commit()
        return self.connection.execute("SELECT changes()").fetchone()[0] == 1

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def sessions(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute("SELECT * FROM sessions ORDER BY rowid")
        ]

    def append_event(self, session_id: str, kind: str, payload: dict[str, Any]) -> int:
        return self.append_events(session_id, [(kind, payload)])[0]

    def append_events(
        self, session_id: str, batch: list[tuple[str, dict[str, Any]]]
    ) -> list[int]:
        if not batch:
            return []
        owns_transaction = not self.connection.in_transaction
        if not owns_transaction:
            raise RuntimeError(
                "append_events cannot run inside an external transaction; "
                "commit events through SessionStore"
            )
        try:
            self.connection.execute("BEGIN")
            seqs = self._append_events_in_transaction(session_id, batch)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        else:
            self._notify_commit(session_id)
            return seqs

    def _append_events_in_transaction(
        self, session_id: str, batch: list[tuple[str, dict[str, Any]]]
    ) -> list[int]:
        seqs = []
        for kind, payload in batch:
            cursor = self.connection.execute(
                "INSERT INTO events(session_id, kind, payload, created_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, kind, json.dumps(payload), _now()),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return an event sequence")
            seqs.append(cursor.lastrowid)
        self.connection.execute(
            "UPDATE sessions SET last_event_seq = ? WHERE id = ?",
            (seqs[-1], session_id),
        )
        return seqs

    def append_event_with_wait(  # noqa: PLR0913 - transaction input fields are explicit
        self,
        session_id: str,
        event_kind: str,
        event_payload: dict[str, Any],
        *,
        wait_id: str,
        kind: str,
        payload: dict[str, Any],
        deadline: str | None = None,
    ) -> int:
        self.connection.execute("BEGIN")
        try:
            seq = self._append_events_in_transaction(
                session_id, [(event_kind, event_payload)]
            )[0]
            self._create_wait(
                wait_id, session_id, kind, deadline, payload, append_event=True
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        else:
            self._notify_commit(session_id)
            return seq

    def _create_wait(
        self,
        wait_id: str,
        session_id: str,
        kind: str,
        deadline: str | None,
        payload: dict[str, Any],
        *,
        append_event: bool,
    ) -> bool:
        if kind not in {"approval", "wake"}:
            raise ValueError("invalid wait kind")
        created = _now()
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO waits(wait_id, session_id, kind, state, "
            "deadline, payload, created_at) "
            "VALUES (?, ?, ?, 'pending', ?, ?, ?)",
            (wait_id, session_id, kind, deadline, json.dumps(payload), created),
        )
        if kind == "wake" and cursor.rowcount:
            self._index_wake_message_ids(wait_id, payload)
        if cursor.rowcount and append_event and kind == "approval":
            self._append_events_in_transaction(
                session_id,
                [("wait_created", {"wait_id": wait_id, "kind": kind})],
            )
        return cursor.rowcount == 1

    def create_wait(
        self,
        wait_id: str,
        session_id: str,
        kind: str,
        deadline: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        self.connection.execute("BEGIN")
        try:
            created = self._create_wait(
                wait_id, session_id, kind, deadline, payload or {}, append_event=True
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        else:
            if created and kind == "approval":
                self._notify_commit(session_id)
            return created

    def resolve_wait(self, wait_id: str, state: str, decision: str) -> bool:
        if state not in {"resolved", "expired", "cancelled"}:
            raise ValueError("invalid wait state")
        self.connection.execute("BEGIN")
        try:
            row = self.connection.execute(
                "SELECT session_id, kind FROM waits "
                "WHERE wait_id = ? AND state = 'pending'",
                (wait_id,),
            ).fetchone()
            if row is None:
                self.connection.rollback()
                return False
            cursor = self.connection.execute(
                "UPDATE waits SET state = ?, decision = ?, resolved_at = ? "
                "WHERE wait_id = ? AND state = 'pending'",
                (state, decision, _now(), wait_id),
            )
            if not cursor.rowcount:
                self.connection.rollback()
                return False
            if row["kind"] == "approval":
                self._append_events_in_transaction(
                    row["session_id"],
                    [
                        (
                            "wait_resolved",
                            {"wait_id": wait_id, "state": state, "decision": decision},
                        )
                    ],
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        else:
            if row["kind"] == "approval":
                self._notify_commit(row["session_id"])
            return True

    def _notify_commit(self, session_id: str) -> None:
        if self.on_commit is not None:
            try:
                self.on_commit(session_id)
            except Exception:
                logger.exception("session store commit hook failed for %s", session_id)

    def set_pending_wait_decision(self, wait_id: str, decision: str | None) -> bool:
        cursor = self.connection.execute(
            "UPDATE waits SET decision = ? WHERE wait_id = ? AND state = 'pending'",
            (decision, wait_id),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def rearm_wake(self, wait_id: str) -> bool:
        cursor = self.connection.execute(
            "UPDATE waits SET state = 'pending', decision = NULL, resolved_at = NULL "
            "WHERE wait_id = ? AND kind = 'wake' AND state = 'resolved' "
            "AND decision != 'pushed'",
            (wait_id,),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def pending_waits(self) -> list[dict[str, Any]]:
        return [
            {**dict(row), "payload": json.loads(row["payload"])}
            for row in self.connection.execute(
                "SELECT * FROM waits WHERE state = 'pending' "
                "ORDER BY created_at, wait_id"
            )
        ]

    def waits_by_kind(
        self, kind: str, state: str | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM waits WHERE kind = ?"
        parameters: tuple[str, ...] = (kind,)
        if state is not None:
            query += " AND state = ?"
            parameters += (state,)
        query += " ORDER BY created_at, rowid"
        return [
            {**dict(row), "payload": json.loads(row["payload"])}
            for row in self.connection.execute(query, parameters)
        ]

    def get_wait(self, wait_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM waits WHERE wait_id = ?", (wait_id,)
        ).fetchone()
        return {**dict(row), "payload": json.loads(row["payload"])} if row else None

    def earliest_deadline(self) -> str | None:
        row = self.connection.execute(
            "SELECT MIN(deadline) FROM waits "
            "WHERE state = 'pending' AND deadline IS NOT NULL AND deadline > ?",
            (_now(),),
        ).fetchone()
        return row[0]

    def pushed_wake_message_ids(self, message_ids: set[str]) -> set[str]:
        pushed: set[str] = set()
        for message_id in message_ids:
            row = self.connection.execute(
                "SELECT 1 FROM wake_message_ids m JOIN waits w USING(wait_id) "
                "WHERE m.message_id = ? AND w.state = 'resolved' "
                "AND w.decision = 'pushed' LIMIT 1",
                (message_id,),
            ).fetchone()
            if row is not None:
                pushed.add(message_id)
        return pushed

    def open_intents(self, session_id: str) -> list[dict[str, Any]]:
        events = self.connection.execute(
            "SELECT * FROM events WHERE session_id = ? AND kind IN "
            "('tool_intent', 'tool_result') ORDER BY seq",
            (session_id,),
        )
        rows = [{**dict(row), "payload": json.loads(row["payload"])} for row in events]
        open_by_call_id: dict[str, dict[str, Any]] = {}
        for event in rows:
            call_id = event["payload"].get("call_id")
            if not isinstance(call_id, str) or not call_id:
                continue
            if event["kind"] == "tool_result":
                open_by_call_id.pop(call_id, None)
            elif call_id not in open_by_call_id:
                open_by_call_id[call_id] = event
        return list(open_by_call_id.values())

    def last_status_event(self, session_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM events WHERE session_id = ? AND kind = 'status' "
            "ORDER BY seq DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return {**dict(row), "payload": json.loads(row["payload"])} if row else None

    def has_status_event(self, session_id: str, status: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM events WHERE session_id = ? AND kind = 'status' "
                "AND json_extract(payload, '$.status') = ? LIMIT 1",
                (session_id, status),
            ).fetchone()
            is not None
        )

    def last_event_at(self, session_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT MAX(created_at) FROM events WHERE session_id = ?", (session_id,)
        ).fetchone()
        return str(row[0]) if row and row[0] is not None else None

    def events_after(
        self, session_id: str, seq: int, limit: int | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM events WHERE session_id = ? AND seq > ? ORDER BY seq"
        values: tuple[Any, ...] = (session_id, seq)
        if limit is not None:
            query += " LIMIT ?"
            values += (limit,)
        return [
            {**dict(row), "payload": json.loads(row["payload"])}
            for row in self.connection.execute(query, values)
        ]

    def recent_usage_payloads(
        self, session_id: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT payload FROM events WHERE session_id = ? AND kind = 'usage'"
            " ORDER BY seq DESC LIMIT ?",
            (session_id, limit),
        )
        return [json.loads(row["payload"]) for row in rows]

    def latest_events(self, session_id: str, limit: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM events WHERE session_id = ? ORDER BY seq DESC LIMIT ?",
            (session_id, limit),
        )
        return [
            {**dict(row), "payload": json.loads(row["payload"])}
            for row in reversed(list(rows))
        ]

    def event_count(self, session_id: str) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM events WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
        )

    def event_count_after(self, session_id: str, seq: int) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM events WHERE session_id = ? AND seq > ?",
                (session_id, seq),
            ).fetchone()[0]
        )

    def event_cursor_bounds(
        self, session_id: str, window_size: int
    ) -> tuple[int | None, int | None]:
        row = self.connection.execute(
            "SELECT MIN(seq), MAX(seq) FROM ("
            "SELECT seq FROM events WHERE session_id = ? "
            "ORDER BY seq DESC LIMIT ?) ",
            (session_id, window_size),
        ).fetchone()
        return row[0], row[1]

    def latest_progress_sequence(
        self, session_id: str, *, through: int | None = None
    ) -> int:
        output_sql, output_params = _agent_output_filter()
        query = (
            "SELECT COALESCE(MAX(seq), 0) FROM events "  # noqa: S608 - allow-list sizes shape parameter placeholders
            f"WHERE session_id = ? AND {output_sql}"
        )
        values: tuple[Any, ...] = (session_id, *output_params)
        if through is not None:
            query += " AND seq <= ?"
            values += (through,)
        return int(self.connection.execute(query, values).fetchone()[0])

    def has_agent_output(self, session_id: str) -> bool:
        output_sql, output_params = _agent_output_filter()
        return (
            self.connection.execute(
                f"SELECT 1 FROM events WHERE session_id = ? AND {output_sql} LIMIT 1",  # noqa: S608 - allow-list sizes shape parameter placeholders
                (session_id, *output_params),
            ).fetchone()
            is not None
        )

    def close(self) -> None:
        self.connection.close()
