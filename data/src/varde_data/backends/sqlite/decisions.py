"""SQLite decision repository."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from varde_core.sqlite import configure_connection
from varde_data.errors import Invalid, NotFound
from varde_data.records.decisions import (
    AnswerEntry,
    AuditEntry,
    DecisionProjection,
    DecisionRecord,
    DeliveredReply,
    SubmitResult,
)
from varde_data.repos.decisions import (
    MAX_PLAN_WRITEBACK_ATTEMPTS,
    AlreadyAnswered,
    IdempotencyConflict,
    validate_decision_id,
)
from varde_data.version import Version

SCHEMA_VERSION = 1


class SqliteDecisions:
    def __init__(
        self, root: Path, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.notes_dir = self.root / "notes"
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "decisions.sqlite3"
        self.audit_path = self.root / "decisions.audit.jsonl"
        self._lock = threading.RLock()
        self._clock = clock
        self._closed_version: Version | None = None
        self.db = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        configure_connection(self.db)
        self.db.execute("PRAGMA synchronous=FULL")
        self._migrate()
        self._sync_audit_file()

    def _migrate(self) -> None:
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise Invalid(
                f"decision database version {version} is newer than supported"
            )
        if version == SCHEMA_VERSION:
            return
        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute("""CREATE TABLE IF NOT EXISTS decisions (
            decision_id TEXT PRIMARY KEY, state TEXT NOT NULL,
            source_msg_ids TEXT NOT NULL DEFAULT '[]', answer_key TEXT,
            kind TEXT NOT NULL DEFAULT 'agent_question',
            record_json TEXT NOT NULL DEFAULT '{}'
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS answers (
            entry_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL,
            idempotency_key TEXT UNIQUE NOT NULL, recipient TEXT NOT NULL,
            body BLOB NOT NULL, status TEXT NOT NULL, notes_path TEXT NOT NULL,
            delivery_msg_id TEXT
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS audit (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, decision_id TEXT NOT NULL,
            prior_state TEXT NOT NULL, new_state TEXT NOT NULL,
            actor TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL,
            msg_ids TEXT NOT NULL
        )""")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(decisions)")}
        if "record_json" not in columns:
            self.db.execute(
                "ALTER TABLE decisions ADD COLUMN record_json TEXT NOT NULL "
                "DEFAULT '{}'"
            )
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (version INTEGER NOT NULL)")
        self.db.execute(
            "INSERT INTO meta(version) SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM meta)"
        )
        self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.db.commit()

    def _bump(self) -> None:
        self.db.execute("UPDATE meta SET version=version+1")

    def _write(self) -> None:
        self._bump()
        self.db.commit()
        self._sync_audit_file()

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise

    def _insert_audit(
        self, decision_id: str, prior: str, new: str, reason: str, msg_ids: list[str]
    ) -> None:
        self.db.execute(
            "INSERT INTO audit(decision_id,prior_state,new_state,actor,at,"
            "reason,msg_ids) "
            "VALUES(?,?,?,'user',?,?,?)",
            (
                decision_id,
                prior,
                new,
                self._clock().isoformat(),
                reason,
                json.dumps(msg_ids),
            ),
        )

    def _sync_audit_file(self) -> None:
        written: set[int] = set()
        if self.audit_path.exists():
            content = self.audit_path.read_bytes()
            if content and not content.endswith(b"\n"):
                boundary = content.rfind(b"\n") + 1
                self.audit_path.write_bytes(content[:boundary])
                content = content[:boundary]
            for line in content.decode("utf-8", errors="replace").splitlines():
                try:
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        written.add(int(payload["seq"]))
                except ValueError, KeyError, TypeError, json.JSONDecodeError:
                    continue
        for row in self.db.execute("SELECT * FROM audit ORDER BY seq"):
            if row["seq"] in written:
                continue
            payload = dict(row)
            payload["msg_ids"] = json.loads(payload["msg_ids"])
            with self.audit_path.open("ab") as stream:
                stream.write(
                    (
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                    ).encode()
                )

    @staticmethod
    def _decision(row: sqlite3.Row) -> DecisionRecord:
        return DecisionRecord(
            row["decision_id"],
            row["state"],
            json.loads(row["source_msg_ids"]),
            row["answer_key"],
            row["kind"],
            json.loads(row["record_json"]),
        )

    @staticmethod
    def _entry(row: sqlite3.Row) -> AnswerEntry:
        return AnswerEntry(
            row["entry_id"],
            row["decision_id"],
            row["idempotency_key"],
            row["recipient"],
            bytes(row["body"]).decode("utf-8"),
            row["status"],
            row["notes_path"],
            row["delivery_msg_id"],
        )

    def project(self, projection: DecisionProjection) -> bool:
        validate_decision_id(projection.decision_id)
        with self._lock, self._write_transaction():
            row = self.db.execute(
                "SELECT * FROM decisions WHERE decision_id=?", (projection.decision_id,)
            ).fetchone()
            if row is not None and row["state"] != "pending":
                self.db.rollback()
                return False
            prior = self._decision(row) if row else None
            record = dict(prior.record) if prior else {}
            now = self._clock().isoformat()
            source_ids = list(prior.source_msg_ids) if prior else []
            if projection.source_id and projection.source_id not in source_ids:
                source_ids.append(projection.source_id)
            record.update(
                {
                    "decision_id": projection.decision_id,
                    "kind": projection.kind,
                    "source_agent": projection.source_agent
                    or record.get("source_agent"),
                    "plan_id": projection.plan_id or record.get("plan_id"),
                    "title": projection.title or record.get("title", ""),
                    "body": projection.body or record.get("body", ""),
                    "context": dict(projection.context),
                    "created_at": record.get("created_at", now),
                    "updated_at": now,
                }
            )
            self.db.execute(
                """INSERT INTO decisions(
                    decision_id,state,source_msg_ids,kind,record_json
                )
                VALUES(?, 'pending', ?, ?, ?) ON CONFLICT(decision_id) DO UPDATE SET
                source_msg_ids=excluded.source_msg_ids,
                kind=excluded.kind, record_json=excluded.record_json
                WHERE decisions.state='pending'""",
                (
                    projection.decision_id,
                    json.dumps(source_ids),
                    projection.kind,
                    json.dumps(record, ensure_ascii=False),
                ),
            )
            self._write()
            return True

    def get_decision(self, decision_id: str) -> DecisionRecord | None:
        with self._lock:
            row = self.db.execute(
                "SELECT * FROM decisions WHERE decision_id=?", (decision_id,)
            ).fetchone()
            return self._decision(row) if row else None

    def list_decisions(
        self, state: str | None = None, kinds: Iterable[str] | None = None
    ) -> list[DecisionRecord]:
        with self._lock:
            rows = self.db.execute("SELECT * FROM decisions ORDER BY rowid").fetchall()
            allowed = set(kinds) if kinds is not None else None
            return [
                self._decision(row)
                for row in rows
                if (state is None or row["state"] == state)
                and (allowed is None or row["kind"] in allowed)
            ]

    def _move(self, decision_id: str, prior: str, new: str, reason: str) -> bool:
        validate_decision_id(decision_id)
        with self._lock, self._write_transaction():
            row = self.db.execute(
                "SELECT state,source_msg_ids FROM decisions WHERE decision_id=?",
                (decision_id,),
            ).fetchone()
            if row is None or row["state"] != prior:
                self.db.rollback()
                return False
            self.db.execute(
                "UPDATE decisions SET state=? WHERE decision_id=? AND state=?",
                (new, decision_id, prior),
            )
            self._insert_audit(
                decision_id, prior, new, reason, json.loads(row["source_msg_ids"])
            )
            self._write()
            return True

    def dismiss(self, decision_id: str) -> bool:
        return self._move(
            decision_id, "pending", "dismissed", "dismissed from the dashboard"
        )

    def restore(self, decision_id: str) -> bool:
        return self._move(
            decision_id, "dismissed", "pending", "restored from the dashboard"
        )

    def submit_answer(
        self, decision_id: str, idempotency_key: str, recipient: str, body: str
    ) -> SubmitResult:
        body.encode("utf-8")
        with self._lock, self._write_transaction():
            row = self.db.execute(
                "SELECT * FROM answers WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if row:
                self.db.rollback()
                existing = self._entry(row)
                if (existing.decision_id, existing.recipient, existing.body) != (
                    decision_id,
                    recipient,
                    body,
                ):
                    raise IdempotencyConflict(
                        "idempotency key conflicts with stored answer"
                    )
                return SubmitResult(existing, True)
            decision = self.db.execute(
                "SELECT * FROM decisions WHERE decision_id=?", (decision_id,)
            ).fetchone()
            if decision is None:
                self.db.execute(
                    "INSERT INTO decisions(decision_id,state,source_msg_ids,kind) "
                    "VALUES(?, 'pending', '[]', 'agent_question')",
                    (decision_id,),
                )
                decision = self.db.execute(
                    "SELECT * FROM decisions WHERE decision_id=?", (decision_id,)
                ).fetchone()
            if decision["state"] != "pending":
                self.db.rollback()
                raise AlreadyAnswered("decision is not pending")
            entry_id = uuid.uuid4().hex
            notes_path = str((self.notes_dir / f"{entry_id}.md").resolve())
            answer = AnswerEntry(
                entry_id,
                decision_id,
                idempotency_key,
                recipient,
                body,
                "stored",
                notes_path,
            )
            self.db.execute(
                "INSERT INTO answers VALUES(?,?,?,?,?,'stored',?,NULL)",
                (
                    entry_id,
                    decision_id,
                    idempotency_key,
                    recipient,
                    body.encode(),
                    notes_path,
                ),
            )
            self.db.execute(
                "UPDATE decisions SET state='answered',answer_key=? "
                "WHERE decision_id=?",
                (idempotency_key, decision_id),
            )
            self._insert_audit(
                decision_id,
                "pending",
                "answered",
                "answer stored",
                json.loads(decision["source_msg_ids"]),
            )
            self._write()
            return SubmitResult(answer, False)

    def transition_entry(
        self,
        entry_id: str,
        new_state: str,
        expected_state: str | set[str],
        reason: str,
        msg_ids: list[str] | None = None,
        delivery_msg_id: str | None = None,
    ) -> bool:
        if not entry_id:
            raise Invalid("entry_id is required")
        with self._lock, self._write_transaction():
            row = self.db.execute(
                "SELECT decision_id,status FROM answers WHERE entry_id=?", (entry_id,)
            ).fetchone()
            expected = (
                {expected_state} if isinstance(expected_state, str) else expected_state
            )
            if row is None or row["status"] not in expected:
                self.db.rollback()
                return False
            decision = self.db.execute(
                "SELECT source_msg_ids FROM decisions WHERE decision_id=?",
                (row["decision_id"],),
            ).fetchone()
            linked = json.loads(decision["source_msg_ids"])
            if delivery_msg_id and delivery_msg_id not in linked:
                linked.append(delivery_msg_id)
                self.db.execute(
                    "UPDATE decisions SET source_msg_ids=? WHERE decision_id=?",
                    (json.dumps(linked), row["decision_id"]),
                )
            audit_ids = list(linked)
            audit_ids.extend(item for item in (msg_ids or []) if item not in audit_ids)
            self.db.execute(
                "UPDATE answers SET status=?,"
                "delivery_msg_id=COALESCE(?,delivery_msg_id) WHERE entry_id=?",
                (new_state, delivery_msg_id, entry_id),
            )
            self._insert_audit(
                row["decision_id"], row["status"], new_state, reason, audit_ids
            )
            self._write()
            return True

    def resolve_permission(self, entry_id: str, success: bool) -> AnswerEntry:
        with self._lock, self._write_transaction():
            row = self.db.execute(
                "SELECT * FROM answers WHERE entry_id=?", (entry_id,)
            ).fetchone()
            if row is None:
                self.db.rollback()
                raise NotFound(entry_id)
            if row["status"] not in {"stored", "failed"}:
                self.db.rollback()
                return self._entry(row)
            decision = self.db.execute(
                "SELECT * FROM decisions WHERE decision_id=?", (row["decision_id"],)
            ).fetchone()
            new_state = "delivered" if success else "failed"
            reason = (
                "permission response sent" if success else "permission response failed"
            )
            self.db.execute(
                "UPDATE answers SET status=? WHERE entry_id=?", (new_state, entry_id)
            )
            self._insert_audit(
                row["decision_id"],
                row["status"],
                new_state,
                reason,
                json.loads(decision["source_msg_ids"]),
            )
            if not success and decision["state"] == "answered":
                self.db.execute(
                    "UPDATE decisions SET state='pending',answer_key=NULL "
                    "WHERE decision_id=?",
                    (row["decision_id"],),
                )
                self._insert_audit(
                    row["decision_id"],
                    "answered",
                    "pending",
                    "permission response failed; request remains open",
                    json.loads(decision["source_msg_ids"]),
                )
            elif success and decision["state"] == "pending":
                self.db.execute(
                    "UPDATE decisions SET state='answered',answer_key=? "
                    "WHERE decision_id=?",
                    (row["idempotency_key"], row["decision_id"]),
                )
                self._insert_audit(
                    row["decision_id"],
                    "pending",
                    "answered",
                    "permission response sent",
                    json.loads(decision["source_msg_ids"]),
                )
            self._write()
            return self._entry(
                self.db.execute(
                    "SELECT * FROM answers WHERE entry_id=?", (entry_id,)
                ).fetchone()
            )

    def entries_by_status(self, status: str) -> list[AnswerEntry]:
        with self._lock:
            return [
                self._entry(row)
                for row in self.db.execute(
                    "SELECT * FROM answers WHERE status=? ORDER BY rowid", (status,)
                )
            ]

    def get_entry(self, idempotency_key: str) -> AnswerEntry | None:
        with self._lock:
            row = self.db.execute(
                "SELECT * FROM answers WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            return self._entry(row) if row else None

    def permission_entry(self, idempotency_key: str) -> bool:
        with self._lock:
            row = self.db.execute(
                "SELECT d.kind FROM answers a JOIN decisions d USING(decision_id) "
                "WHERE a.idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            return bool(row and row["kind"] == "permission")

    def latest_delivered_reply(self, decision_id: str) -> DeliveredReply | None:
        with self._lock:
            row = self.db.execute(
                "SELECT a.body, (SELECT at FROM audit WHERE decision_id=a.decision_id "
                "AND new_state='delivered' ORDER BY seq DESC LIMIT 1) AS sent_at "
                "FROM answers a WHERE a.decision_id=? AND a.status='delivered' "
                "ORDER BY a.rowid DESC LIMIT 1",
                (decision_id,),
            ).fetchone()
            if row is None or row["sent_at"] is None:
                return None
            return DeliveredReply(bytes(row["body"]).decode("utf-8"), row["sent_at"])

    def writeback_candidates(
        self, attempt_cap: int = MAX_PLAN_WRITEBACK_ATTEMPTS
    ) -> list[AnswerEntry]:
        with self._lock:
            rows = self.db.execute(
                "SELECT a.* FROM answers a WHERE a.status='delivered' "
                "AND (SELECT count(*) FROM audit f WHERE f.decision_id=a.decision_id "
                "AND f.new_state='plan-write-failed' AND f.reason LIKE "
                "a.entry_id || ':%') BETWEEN 1 AND ? "
                "AND NOT EXISTS (SELECT 1 FROM audit s WHERE "
                "s.decision_id=a.decision_id AND s.new_state='plan-written' "
                "AND s.reason LIKE a.entry_id || ':%') ORDER BY a.rowid",
                (attempt_cap - 1,),
            ).fetchall()
            return [self._entry(row) for row in rows]

    def get_entry_by_id(self, entry_id: str) -> AnswerEntry | None:
        with self._lock:
            row = self.db.execute(
                "SELECT * FROM answers WHERE entry_id=?", (entry_id,)
            ).fetchone()
            return self._entry(row) if row else None

    def record_writeback_audit(
        self, decision_id: str, state: str, entry_id: str, reason: str
    ) -> None:
        validate_decision_id(decision_id)
        with self._lock, self._write_transaction():
            row = self.db.execute(
                "SELECT source_msg_ids FROM decisions WHERE decision_id=?",
                (decision_id,),
            ).fetchone()
            if row is None:
                raise NotFound(decision_id)
            self._insert_audit(
                decision_id,
                "delivered",
                state,
                f"{entry_id}: {reason}",
                json.loads(row["source_msg_ids"]),
            )
            self._write()

    def audit_rows(self, decision_id: str | None = None) -> list[AuditEntry]:
        with self._lock:
            rows = self.db.execute(
                "SELECT * FROM audit WHERE (? IS NULL OR decision_id=?) ORDER BY seq",
                (decision_id, decision_id),
            )
            return [
                AuditEntry(
                    row["seq"],
                    row["decision_id"],
                    row["prior_state"],
                    row["new_state"],
                    row["actor"],
                    row["at"],
                    row["reason"],
                    json.loads(row["msg_ids"]),
                )
                for row in rows
            ]

    def write_answer_note(self, entry_id: str, body: bytes) -> str:
        with self._lock, self._write_transaction():
            row = self.db.execute(
                "SELECT notes_path FROM answers WHERE entry_id=?", (entry_id,)
            ).fetchone()
            if row is None:
                raise NotFound(entry_id)
            target = Path(row["notes_path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            self._write()
            return str(target)

    def notes_path(self, entry_id: str) -> str:
        return str((self.notes_dir / f"{entry_id}.md").resolve())

    def version(self) -> Version:
        if self._closed_version is not None:
            return self._closed_version
        with self._lock:
            row = self.db.execute("SELECT version FROM meta").fetchone()
            return Version(row[0] if row else 0)

    def close(self) -> None:
        with self._lock:
            self._closed_version = self.version()
            self.db.close()
