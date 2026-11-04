"""SQLite work item repository."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager, suppress
from pathlib import Path
from typing import Any

from varde_core.sqlite import configure_connection
from varde_data.errors import Invalid, NotFound
from varde_data.records.workitems import AuditEntry, Question, WorkItem
from varde_data.repos.workitems import validate_new_item
from varde_data.version import Version

SCHEMA_VERSION = 1


class SqliteWorkItems:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.notes_dir = self.root / "workitem-notes"
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "workitems.sqlite3"
        with self._connection() as db:
            self._migrate(db)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        configure_connection(db)
        return db

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as db, db:
            yield db

    @staticmethod
    def _migrate(db: sqlite3.Connection) -> None:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise Invalid(
                f"work item database version {version} is newer than supported"
            )
        if version == SCHEMA_VERSION:
            return
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS work_items (
            id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
            text TEXT NOT NULL, project TEXT NOT NULL, state TEXT NOT NULL,
            notes_path TEXT NOT NULL, planner_session TEXT, plan_path TEXT,
            plan_ready_id TEXT, launch_request_id TEXT, launch_request_notes TEXT
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS work_item_audit (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL,
            prior_state TEXT, new_state TEXT NOT NULL, detail TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS work_item_questions (
            item_id TEXT NOT NULL, msg_id TEXT NOT NULL, payload TEXT NOT NULL,
            answer TEXT, answer_key TEXT, PRIMARY KEY(item_id, msg_id)
        )""")
        self_columns = {r[1] for r in db.execute("PRAGMA table_info(work_items)")}
        for name in ("launch_request_id", "launch_request_notes"):
            if name not in self_columns:
                db.execute(f"ALTER TABLE work_items ADD COLUMN {name} TEXT")
        question_columns = {
            r[1] for r in db.execute("PRAGMA table_info(work_item_questions)")
        }
        if "answer_key" not in question_columns:
            db.execute("ALTER TABLE work_item_questions ADD COLUMN answer_key TEXT")
        db.execute("CREATE TABLE IF NOT EXISTS meta (version INTEGER NOT NULL)")
        db.execute(
            "INSERT INTO meta(version) SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM meta)"
        )
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @staticmethod
    def _item(row: sqlite3.Row) -> WorkItem:
        return WorkItem(**dict(row))

    @staticmethod
    def _bump(db: sqlite3.Connection) -> None:
        db.execute("UPDATE meta SET version=version+1")

    @staticmethod
    def _audit(
        db: sqlite3.Connection, item_id: str, prior: str | None, new: str, detail: str
    ) -> None:
        db.execute(
            "INSERT INTO work_item_audit(item_id,prior_state,new_state,detail) "
            "VALUES(?,?,?,?)",
            (item_id, prior, new, detail),
        )

    def create(self, key: str, text: str, project: str) -> WorkItem:
        validate_new_item(key, text, project)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            found = db.execute(
                "SELECT * FROM work_items WHERE idempotency_key=?", (key,)
            ).fetchone()
            if found:
                return self._item(found)
            item_id = uuid.uuid4().hex
            note_path = (self.notes_dir / item_id / "request.md").resolve()
            note_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                note_path.write_text(text, encoding="utf-8")
                db.execute(
                    "INSERT INTO work_items(id,idempotency_key,text,project,state,"
                    "notes_path) "
                    "VALUES(?,?,?,?,?,?)",
                    (item_id, key, text, project, "new", str(note_path)),
                )
                self._audit(db, item_id, None, "new", "submitted")
                self._bump(db)
            except BaseException:
                with suppress(OSError):
                    note_path.unlink(missing_ok=True)
                with suppress(OSError):
                    note_path.parent.rmdir()
                raise
            return self._item(
                db.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
            )

    def get(self, item_id: str) -> WorkItem:
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM work_items WHERE id=?", (item_id,)
            ).fetchone()
        if row is None:
            raise NotFound(item_id)
        return self._item(row)

    def by_key(self, key: str) -> WorkItem | None:
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM work_items WHERE idempotency_key=?", (key,)
            ).fetchone()
        return self._item(row) if row else None

    def list(self) -> list[WorkItem]:
        with self._connection() as db:
            return [
                self._item(r)
                for r in db.execute("SELECT * FROM work_items ORDER BY rowid")
            ]

    def for_planner_session(self, session_id: str) -> WorkItem | None:
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM work_items WHERE planner_session=?", (session_id,)
            ).fetchone()
        return self._item(row) if row else None

    def _update(
        self,
        item_id: str,
        sql: str,
        args: tuple[Any, ...],
        *,
        audit: tuple[str | None, str, str] | None = None,
    ) -> bool:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            cur = db.execute(sql, (*args, item_id))
            if cur.rowcount:
                if audit:
                    self._audit(db, item_id, *audit)
                self._bump(db)
            return cur.rowcount == 1

    def start_planning(self, item_id: str, session_id: str) -> WorkItem:
        item = self.get(item_id)
        if item.state == "new":
            self._update(
                item_id,
                "UPDATE work_items SET state='planning',planner_session=? "
                "WHERE id=? AND state='new'",
                (session_id,),
                audit=("new", "planning", "planner started"),
            )
        return self.get(item_id)

    def claim_planner_start(self, item_id: str) -> bool:
        return self._update(
            item_id,
            "UPDATE work_items SET state='planning' WHERE id=? AND state='new'",
            (),
            audit=("new", "planning", "planner start claimed"),
        )

    def attach_planner(self, item_id: str, session_id: str) -> WorkItem:
        self._update(
            item_id,
            "UPDATE work_items SET planner_session=? WHERE planner_session IS NOT ? "
            "AND id=? AND state IN ('planning','asking')",
            (session_id, session_id),
        )
        return self.get(item_id)

    def reset_planner_start(self, item_id: str) -> WorkItem:
        item = self.get(item_id)
        if item.state == "planning" and item.planner_session is None:
            self._update(
                item_id,
                "UPDATE work_items SET state='new' WHERE id=? "
                "AND state='planning' AND planner_session IS NULL",
                (),
                audit=("planning", "new", "planner start recovered for retry"),
            )
        return self.get(item_id)

    def fail(self, item_id: str, detail: str) -> WorkItem:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state FROM work_items WHERE id=?", (item_id,)
            ).fetchone()
            if row is None:
                raise NotFound(item_id)
            state = row["state"]
            if state not in {"rejected", "failed", "queued"}:
                db.execute(
                    "UPDATE work_items SET state='failed' WHERE id=?", (item_id,)
                )
                self._audit(db, item_id, state, "failed", detail)
                self._bump(db)
        return self.get(item_id)

    def record_question(
        self, item_id: str, msg_id: str, payload: Mapping[str, object]
    ) -> bool:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            item = db.execute(
                "SELECT state FROM work_items WHERE id=?", (item_id,)
            ).fetchone()
            if item is None:
                raise NotFound(item_id)
            if item["state"] not in {"planning", "asking"}:
                raise Invalid("work item is not planning")
            cur = db.execute(
                "INSERT OR IGNORE INTO work_item_questions(item_id,msg_id,payload) "
                "VALUES(?,?,?)",
                (item_id, msg_id, json.dumps(dict(payload), ensure_ascii=False)),
            )
            if not cur.rowcount:
                return False
            if item["state"] == "planning":
                db.execute(
                    "UPDATE work_items SET state='asking' WHERE id=?", (item_id,)
                )
                self._audit(db, item_id, "planning", "asking", f"question {msg_id}")
            self._bump(db)
            return True

    def answer(self, item_id: str, msg_id: str, text: str, key: str) -> bool:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT answer,answer_key FROM work_item_questions "
                "WHERE item_id=? AND msg_id=?",
                (item_id, msg_id),
            ).fetchone()
            if row is None:
                raise NotFound(msg_id)
            if row["answer"] is not None or row["answer_key"] is not None:
                return False
            db.execute(
                "UPDATE work_item_questions SET answer=?,answer_key=? "
                "WHERE item_id=? AND msg_id=?",
                (text, key, item_id, msg_id),
            )
            pending = db.execute(
                "SELECT 1 FROM work_item_questions WHERE item_id=? AND answer IS NULL",
                (item_id,),
            ).fetchone()
            if not pending:
                db.execute(
                    "UPDATE work_items SET state='planning' WHERE id=?", (item_id,)
                )
                self._audit(
                    db, item_id, "asking", "planning", f"question {msg_id} answered"
                )
            self._bump(db)
            return True

    def plan_ready(self, item_id: str, plan_path: str, message_id: str) -> WorkItem:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state,plan_ready_id FROM work_items WHERE id=?", (item_id,)
            ).fetchone()
            if row is None:
                raise NotFound(item_id)
            if row["plan_ready_id"]:
                return self.get(item_id)
            if row["state"] not in {"planning", "asking"}:
                raise Invalid("work item cannot become ready from its current state")
            db.execute(
                "UPDATE work_items SET state='ready',plan_path=?,plan_ready_id=? "
                "WHERE id=?",
                (plan_path, message_id, item_id),
            )
            self._audit(db, item_id, row["state"], "ready", "plan ready")
            self._bump(db)
        return self.get(item_id)

    def decide(self, item_id: str, approved: bool) -> WorkItem:
        target = "queued" if approved else "rejected"
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state FROM work_items WHERE id=?", (item_id,)
            ).fetchone()
            if row is None:
                raise NotFound(item_id)
            if row["state"] in {"approved", "rejected", "queued", "failed"}:
                return self.get(item_id)
            if row["state"] != "ready":
                raise Invalid("only a ready plan can be approved or rejected")
            db.execute("UPDATE work_items SET state=? WHERE id=?", (target, item_id))
            self._audit(db, item_id, "ready", target, "user decision")
            self._bump(db)
        return self.get(item_id)

    def claim_launch_request(self, item_id: str, notes_path: str) -> bool:
        return self._update(
            item_id,
            "UPDATE work_items SET state='queued',launch_request_id='sending',"
            "launch_request_notes=? WHERE id=? AND state IN ('ready','queued') "
            "AND launch_request_id IS NULL",
            (notes_path,),
            audit=("ready", "queued", "launch request claimed"),
        )

    def record_launch_request(
        self, item_id: str, message_id: str, notes_path: str
    ) -> WorkItem:
        self._update(
            item_id,
            "UPDATE work_items SET launch_request_id=?,launch_request_notes=? "
            "WHERE id=? AND state='queued' AND launch_request_id='sending'",
            (message_id, notes_path),
        )
        return self.get(item_id)

    def release_launch_request(self, item_id: str) -> None:
        self._update(
            item_id,
            "UPDATE work_items SET launch_request_id=NULL WHERE id=? "
            "AND state='queued' AND launch_request_id='sending'",
            (),
        )

    def questions(self, item_id: str) -> list[Question]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM work_item_questions WHERE item_id=? ORDER BY msg_id",
                (item_id,),
            ).fetchall()
        return [
            Question(
                r["item_id"],
                r["msg_id"],
                json.loads(r["payload"]),
                r["answer"],
                r["answer_key"],
            )
            for r in rows
        ]

    def audit(self, item_id: str) -> list[AuditEntry]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM work_item_audit WHERE item_id=? ORDER BY seq", (item_id,)
            ).fetchall()
        return [
            AuditEntry(
                r["seq"], r["item_id"], r["prior_state"], r["new_state"], r["detail"]
            )
            for r in rows
        ]

    def version(self) -> Version:
        with self._connection() as db:
            return Version(db.execute("SELECT version FROM meta").fetchone()[0])

    def write_note(self, item_id: str, name: str, text: str) -> str:
        self.get(item_id)
        if not name or name == ".":
            raise Invalid("note name must identify a file")
        if "\x00" in name:
            raise Invalid("note name must not contain NUL")
        base = (self.notes_dir / item_id).resolve()
        target = (base / name).resolve()
        if not target.is_relative_to(base):
            raise Invalid("note path must stay inside the work item")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._bump(db)
        return str(target)

    def owns_note(self, item_id: str, path: str) -> bool:
        try:
            self.get(item_id)
            return (
                Path(path)
                .resolve()
                .is_relative_to((self.notes_dir / item_id).resolve())
            )
        except OSError, ValueError, NotFound:
            return False

    def close(self) -> None:
        return None
