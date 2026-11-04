"""SQLite chat repository."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from varde_core.sqlite import (
    configure_connection_options,
    configure_journal_mode,
)
from varde_data.errors import Invalid, NotFound
from varde_data.records.chat import (
    ChatBot,
    ChatMessage,
    ChatThread,
    ChatTurn,
    Takeover,
    TakeoverQueueItem,
)

SCHEMA_VERSION = 3


@dataclass(frozen=True)
class _MessageDraft:
    message_id: str
    thread_key: str
    reply_to: str | None
    role: str
    kind: str | None
    text: str
    link: str | None
    state: str
    source_agent_id: str | None = None
    source_event_seq: int | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _agent_id(thread_key: str) -> str:
    prefix = "instance:"
    if not thread_key.startswith(prefix) or not thread_key[len(prefix) :]:
        raise Invalid("takeover operations require an instance thread")
    return thread_key[len(prefix) :]


class SqliteChat:
    """Threaded chat messages and takeover state in one dashboard database."""

    def __init__(
        self,
        working_dir: Path,
        clock: Callable[[], str] = _now,
    ) -> None:
        self.root = Path(working_dir)
        self.path = self.root / ".cache" / "dashboard" / "chat.sqlite3"
        self._clock = clock
        self._lock = threading.RLock()
        with self._connection() as db:
            configure_journal_mode(db)
            self._migrate(db)
            self._ensure_main_thread(db)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        configure_connection_options(db)
        try:
            with closing(db), db:
                yield db
        except BaseException:
            db.close()
            raise

    def _migrate(self, db: sqlite3.Connection) -> None:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise Invalid(f"chat database version {version} is newer than supported")
        if version == SCHEMA_VERSION:
            return
        db.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS chat_threads (
                thread_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL CHECK(kind IN ('main', 'instance')),
                agent_id TEXT,
                plan_id TEXT,
                label TEXT,
                created_at TEXT NOT NULL,
                archived_at TEXT
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                change_seq INTEGER NOT NULL,
                id TEXT NOT NULL UNIQUE,
                thread_key TEXT NOT NULL REFERENCES chat_threads(thread_key),
                reply_to TEXT,
                role TEXT NOT NULL CHECK(role IN ('user', 'bot', 'event')),
                kind TEXT,
                text TEXT NOT NULL,
                link TEXT,
                state TEXT NOT NULL,
                source_agent_id TEXT,
                source_event_seq INTEGER,
                created_at TEXT NOT NULL,
                UNIQUE(source_agent_id, source_event_seq)
            );
            CREATE INDEX IF NOT EXISTS chat_messages_thread_seq
                ON chat_messages(thread_key, seq);
            CREATE INDEX IF NOT EXISTS chat_messages_thread_change
                ON chat_messages(thread_key, change_seq);
            CREATE TABLE IF NOT EXISTS chat_delivery (
                thread_key TEXT NOT NULL,
                message_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('queued', 'sent')),
                PRIMARY KEY(thread_key, message_id),
                FOREIGN KEY(message_id)
                    REFERENCES chat_messages(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS chat_delivery_ready
                ON chat_delivery(state, thread_key, message_id);
            CREATE TABLE IF NOT EXISTS chat_turns (
                agent_id TEXT NOT NULL,
                first_event_seq INTEGER NOT NULL,
                last_event_seq INTEGER,
                PRIMARY KEY(agent_id, first_event_seq)
            );
            CREATE TABLE IF NOT EXISTS chat_projection_cursors (
                agent_id TEXT PRIMARY KEY,
                processed_event_seq INTEGER NOT NULL
            );
            -- Legacy source_event_seq identifies the turn's first event. Back up
            -- one so a restart replays that message and any unprojected tail.
            INSERT OR IGNORE INTO chat_projection_cursors(agent_id, processed_event_seq)
            SELECT source_agent_id, MAX(source_event_seq) - 1
            FROM chat_messages
            WHERE role='bot' AND source_agent_id IS NOT NULL
                AND source_event_seq IS NOT NULL
            GROUP BY source_agent_id;
            CREATE TABLE IF NOT EXISTS chat_bot (
                key TEXT PRIMARY KEY REFERENCES chat_threads(thread_key),
                agent_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                context_tokens INTEGER,
                state TEXT NOT NULL,
                generation INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS takeover (
                agent_id TEXT PRIMARY KEY,
                holder_client TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                released_at TEXT
            );
            CREATE TABLE IF NOT EXISTS takeover_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                queued_at TEXT NOT NULL,
                delivered_at TEXT,
                dropped_reason TEXT,
                request_id TEXT,
                UNIQUE(agent_id, request_id)
            );
            CREATE INDEX IF NOT EXISTS takeover_queue_ready
                ON takeover_queue(agent_id, delivered_at, dropped_reason, id);
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO meta(key, value) VALUES ('change_seq', 0);
            PRAGMA user_version = 3;
            COMMIT;
            """
        )

    def _ensure_main_thread(self, db: sqlite3.Connection) -> None:
        db.execute(
            "INSERT OR IGNORE INTO chat_threads "
            "(thread_key, kind, created_at) VALUES ('main', 'main', ?)",
            (self._clock(),),
        )

    @staticmethod
    def _message(row: sqlite3.Row) -> ChatMessage:
        return ChatMessage(**dict(row))

    @staticmethod
    def _thread(row: sqlite3.Row) -> ChatThread:
        return ChatThread(**dict(row))

    @staticmethod
    def _bot(row: sqlite3.Row) -> ChatBot:
        return ChatBot(**dict(row))

    @staticmethod
    def _turn(row: sqlite3.Row) -> ChatTurn:
        return ChatTurn(**dict(row))

    @staticmethod
    def _takeover(row: sqlite3.Row) -> Takeover:
        return Takeover(**dict(row))

    @staticmethod
    def _queue_item(row: sqlite3.Row) -> TakeoverQueueItem:
        return TakeoverQueueItem(**dict(row))

    @staticmethod
    def _require_thread(db: sqlite3.Connection, thread_key: str) -> None:
        if (
            db.execute(
                "SELECT 1 FROM chat_threads WHERE thread_key=?", (thread_key,)
            ).fetchone()
            is None
        ):
            raise NotFound(thread_key)

    def _next_change(self, db: sqlite3.Connection) -> int:
        db.execute("UPDATE meta SET value=value+1 WHERE key='change_seq'")
        return int(
            db.execute("SELECT value FROM meta WHERE key='change_seq'").fetchone()[0]
        )

    def _insert_message(
        self,
        db: sqlite3.Connection,
        draft: _MessageDraft,
    ) -> ChatMessage:
        change_seq = self._next_change(db)
        db.execute(
            "INSERT INTO chat_messages(change_seq,id,thread_key,reply_to,role,kind,"
            "text,link,state,source_agent_id,source_event_seq,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                change_seq,
                draft.message_id,
                draft.thread_key,
                draft.reply_to,
                draft.role,
                draft.kind,
                draft.text,
                draft.link,
                draft.state,
                draft.source_agent_id,
                draft.source_event_seq,
                self._clock(),
            ),
        )
        row = db.execute(
            "SELECT * FROM chat_messages WHERE thread_key=? AND id=?",
            (draft.thread_key, draft.message_id),
        ).fetchone()
        return self._message(row)

    def append_user(
        self, thread_key: str, message_id: str, text: str, reply_to: str | None = None
    ) -> ChatMessage:
        return self.append_user_once(thread_key, message_id, text, reply_to)[0]

    def append_user_once(
        self, thread_key: str, message_id: str, text: str, reply_to: str | None = None
    ) -> tuple[ChatMessage, bool]:
        if not message_id or not text:
            raise Invalid("chat user message id and text are required")
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_thread(db, thread_key)
            existing = db.execute(
                "SELECT * FROM chat_messages WHERE thread_key=? AND id=?",
                (thread_key, message_id),
            ).fetchone()
            if existing:
                return self._message(existing), False
            if (
                db.execute(
                    "SELECT 1 FROM chat_messages WHERE thread_key=? AND id=? "
                    "AND role IN ('user','bot')",
                    (thread_key, reply_to),
                ).fetchone()
                is None
                and reply_to is not None
            ):
                raise Invalid(
                    "reply_to must identify a user or bot message in this thread"
                )
            message = self._insert_message(
                db,
                _MessageDraft(
                    message_id,
                    thread_key,
                    reply_to,
                    "user",
                    None,
                    text,
                    None,
                    "sent",
                ),
            )
            db.execute(
                "INSERT INTO chat_delivery(thread_key,message_id,state) VALUES(?,?,?)",
                (thread_key, message_id, "queued"),
            )
            return message, True

    def pending_user_messages(self) -> Sequence[ChatMessage]:
        with self._lock, self._connection() as db:
            rows = db.execute(
                "SELECT chat_messages.* FROM chat_messages JOIN chat_delivery "
                "ON chat_delivery.thread_key=chat_messages.thread_key "
                "AND chat_delivery.message_id=chat_messages.id "
                "WHERE chat_delivery.state='queued' "
                "ORDER BY chat_messages.thread_key,chat_messages.seq"
            ).fetchall()
            return tuple(self._message(row) for row in rows)

    def mark_user_delivered(self, thread_key: str, message_id: str) -> bool:
        with self._lock, self._connection() as db:
            cursor = db.execute(
                "UPDATE chat_delivery SET state='sent' "
                "WHERE thread_key=? AND message_id=? AND state='queued'",
                (thread_key, message_id),
            )
            return cursor.rowcount == 1

    def append_bot(
        self,
        thread_key: str,
        source_agent_id: str,
        source_event_seq: int,
        text: str,
        state: str = "final",
    ) -> ChatMessage:
        if state not in {"streaming", "final"}:
            raise Invalid("bot message state must be 'streaming' or 'final'")
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_thread(db, thread_key)
            existing = db.execute(
                "SELECT * FROM chat_messages WHERE thread_key=? AND "
                "source_agent_id=? AND source_event_seq=?",
                (thread_key, source_agent_id, source_event_seq),
            ).fetchone()
            if existing:
                return self._message(existing)
            return self._insert_message(
                db,
                _MessageDraft(
                    uuid.uuid4().hex,
                    thread_key,
                    None,
                    "bot",
                    None,
                    text,
                    None,
                    state,
                    source_agent_id,
                    source_event_seq,
                ),
            )

    def update_bot_text(
        self, thread_key: str, message_id: str, text: str, state: str | None = None
    ) -> ChatMessage:
        if state is not None and state not in {"streaming", "final"}:
            raise Invalid("bot message state must be 'streaming' or 'final'")
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM chat_messages WHERE thread_key=? AND id=? "
                "AND role='bot'",
                (thread_key, message_id),
            ).fetchone()
            if row is None:
                raise NotFound(message_id)
            change_seq = self._next_change(db)
            db.execute(
                "UPDATE chat_messages SET text=?, state=?, change_seq=? "
                "WHERE thread_key=? AND id=? AND role='bot'",
                (text, state or row["state"], change_seq, thread_key, message_id),
            )
            updated = db.execute(
                "SELECT * FROM chat_messages WHERE thread_key=? AND id=?",
                (thread_key, message_id),
            ).fetchone()
            return self._message(updated)

    def append_event(
        self, kind: str, summary: str, link: str | None, thread_key: str = "main"
    ) -> ChatMessage:
        if not kind or not summary:
            raise Invalid("chat event kind and summary are required")
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_thread(db, thread_key)
            return self._insert_message(
                db,
                _MessageDraft(
                    uuid.uuid4().hex,
                    thread_key,
                    None,
                    "event",
                    kind,
                    summary,
                    link,
                    "final",
                ),
            )

    def page(
        self, thread_key: str, before: int | None = None, limit: int = 50
    ) -> Sequence[ChatMessage]:
        if limit <= 0:
            raise Invalid("page limit must be positive")
        with self._connection() as db:
            self._require_thread(db, thread_key)
            if before is None:
                rows = db.execute(
                    "SELECT * FROM chat_messages WHERE thread_key=? "
                    "ORDER BY seq DESC LIMIT ?",
                    (thread_key, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM chat_messages WHERE thread_key=? AND seq<? "
                    "ORDER BY seq DESC LIMIT ?",
                    (thread_key, before, limit),
                ).fetchall()
        return tuple(self._message(row) for row in reversed(rows))

    def latest_bot_event_sequences(self) -> dict[str, int]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT source_agent_id, MAX(source_event_seq) "
                "FROM chat_messages WHERE role='bot' "
                "AND source_agent_id IS NOT NULL "
                "AND source_event_seq IS NOT NULL GROUP BY source_agent_id"
            ).fetchall()
        return {str(agent_id): int(sequence) for agent_id, sequence in rows}

    def processed_event_sequences(self) -> dict[str, int]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT agent_id, processed_event_seq FROM chat_projection_cursors"
            ).fetchall()
        return {str(agent_id): int(sequence) for agent_id, sequence in rows}

    def save_processed_event_sequence(self, agent_id: str, sequence: int) -> None:
        if not agent_id or sequence < 0:
            raise Invalid(
                "projection cursor requires an agent and nonnegative sequence"
            )
        with self._lock, self._connection() as db:
            db.execute(
                "INSERT INTO chat_projection_cursors(agent_id, processed_event_seq) "
                "VALUES(?, ?) ON CONFLICT(agent_id) DO UPDATE SET "
                "processed_event_seq=MAX(processed_event_seq, "
                "excluded.processed_event_seq)",
                (agent_id, sequence),
            )

    def changes_after(self, thread_key: str, change_seq: int) -> Sequence[ChatMessage]:
        with self._connection() as db:
            self._require_thread(db, thread_key)
            rows = db.execute(
                "SELECT * FROM chat_messages WHERE thread_key=? AND change_seq>? "
                "ORDER BY change_seq, seq",
                (thread_key, change_seq),
            ).fetchall()
        return tuple(self._message(row) for row in rows)

    def create_thread(
        self,
        thread_key: str,
        kind: str = "instance",
        agent_id: str | None = None,
        plan_id: str | None = None,
        label: str | None = None,
    ) -> ChatThread:
        if kind != "instance" or agent_id is None or not agent_id:
            raise Invalid("new chat threads must be instance threads with an agent id")
        if thread_key != f"instance:{agent_id}":
            raise Invalid("instance thread key must match its agent id")
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM chat_threads WHERE thread_key=?", (thread_key,)
            ).fetchone()
            if existing:
                if existing["agent_id"] != agent_id:
                    raise Invalid("chat thread already belongs to another agent")
                if label and existing["label"] != label:
                    db.execute(
                        "UPDATE chat_threads SET label=? WHERE thread_key=?",
                        (label, thread_key),
                    )
                    existing = db.execute(
                        "SELECT * FROM chat_threads WHERE thread_key=?", (thread_key,)
                    ).fetchone()
                return self._thread(existing)
            db.execute(
                "INSERT INTO chat_threads(thread_key,kind,agent_id,plan_id,label,"
                "created_at) "
                "VALUES(?, 'instance', ?, ?, ?, ?)",
                (thread_key, agent_id, plan_id, label, self._clock()),
            )
            return self._thread(
                db.execute(
                    "SELECT * FROM chat_threads WHERE thread_key=?", (thread_key,)
                ).fetchone()
            )

    def get_thread(self, thread_key: str) -> ChatThread:
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM chat_threads WHERE thread_key=?", (thread_key,)
            ).fetchone()
        if row is None:
            raise NotFound(thread_key)
        return self._thread(row)

    def archive_thread(
        self, thread_key: str, archived_at: str | None = None
    ) -> ChatThread:
        if thread_key == "main":
            raise Invalid("the main chat thread cannot be archived")
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_thread(db, thread_key)
            db.execute(
                "UPDATE chat_threads SET archived_at=COALESCE(archived_at, ?) "
                "WHERE thread_key=?",
                (archived_at or self._clock(), thread_key),
            )
            return self._thread(
                db.execute(
                    "SELECT * FROM chat_threads WHERE thread_key=?", (thread_key,)
                ).fetchone()
            )

    def set_chat_bot(
        self,
        thread_key: str,
        agent_id: str,
        started_at: str,
        context_tokens: int | None,
        state: str,
        generation: int,
    ) -> ChatBot:
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_thread(db, thread_key)
            db.execute(
                "INSERT INTO chat_bot(key,agent_id,started_at,context_tokens,state,"
                "generation) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                "agent_id=excluded.agent_id,started_at=excluded.started_at,"
                "context_tokens=excluded.context_tokens,state=excluded.state,"
                "generation=excluded.generation",
                (thread_key, agent_id, started_at, context_tokens, state, generation),
            )
            return self._bot(
                db.execute(
                    "SELECT * FROM chat_bot WHERE key=?", (thread_key,)
                ).fetchone()
            )

    def get_chat_bot(self, thread_key: str) -> ChatBot | None:
        with self._connection() as db:
            self._require_thread(db, thread_key)
            row = db.execute(
                "SELECT * FROM chat_bot WHERE key=?", (thread_key,)
            ).fetchone()
        return self._bot(row) if row else None

    def record_turn(
        self,
        thread_key: str,
        agent_id: str,
        first_event_seq: int,
        last_event_seq: int | None,
    ) -> ChatTurn:
        if thread_key != "main":
            raise Invalid("chat turns are recorded only for the main thread")
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO chat_turns(agent_id,first_event_seq,last_event_seq) "
                "VALUES(?,?,?) ON CONFLICT(agent_id,first_event_seq) DO UPDATE SET "
                "last_event_seq=excluded.last_event_seq",
                (agent_id, first_event_seq, last_event_seq),
            )
            return self._turn(
                db.execute(
                    "SELECT * FROM chat_turns WHERE agent_id=? AND first_event_seq=?",
                    (agent_id, first_event_seq),
                ).fetchone()
            )

    def acquire(self, thread_key: str, holder_client: str, now: str) -> Takeover | None:
        agent_id = _agent_id(thread_key)
        if not holder_client:
            raise Invalid("takeover holder is required")
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_thread(db, thread_key)
            row = db.execute(
                "SELECT * FROM takeover WHERE agent_id=?", (agent_id,)
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO takeover(agent_id,holder_client,acquired_at,"
                    "heartbeat_at) "
                    "VALUES(?,?,?,?)",
                    (agent_id, holder_client, now, now),
                )
            elif row["released_at"] is None and row["holder_client"] != holder_client:
                return None
            elif row["released_at"] is None:
                db.execute(
                    "UPDATE takeover SET heartbeat_at=? WHERE agent_id=?",
                    (now, agent_id),
                )
            else:
                db.execute(
                    "UPDATE takeover SET holder_client=?,acquired_at=?,heartbeat_at=?,"
                    "released_at=NULL WHERE agent_id=?",
                    (holder_client, now, now, agent_id),
                )
            return self._takeover(
                db.execute(
                    "SELECT * FROM takeover WHERE agent_id=?", (agent_id,)
                ).fetchone()
            )

    def get_takeover(self, thread_key: str) -> Takeover | None:
        agent_id = _agent_id(thread_key)
        with self._connection() as db:
            self._require_thread(db, thread_key)
            row = db.execute(
                "SELECT * FROM takeover WHERE agent_id=?", (agent_id,)
            ).fetchone()
        return self._takeover(row) if row else None

    def heartbeat(self, thread_key: str, holder_client: str, now: str) -> bool:
        agent_id = _agent_id(thread_key)
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_thread(db, thread_key)
            return (
                db.execute(
                    "UPDATE takeover SET heartbeat_at=? WHERE agent_id=? "
                    "AND holder_client=? AND released_at IS NULL",
                    (now, agent_id, holder_client),
                ).rowcount
                == 1
            )

    def release(self, thread_key: str, holder_client: str, now: str) -> bool:
        agent_id = _agent_id(thread_key)
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_thread(db, thread_key)
            return (
                db.execute(
                    "UPDATE takeover SET released_at=? WHERE agent_id=? "
                    "AND holder_client=? AND released_at IS NULL",
                    (now, agent_id, holder_client),
                ).rowcount
                == 1
            )

    def enqueue(
        self,
        thread_key: str,
        sender: str,
        kind: str,
        text: str,
        queued_at: str,
        request_id: str | None = None,
    ) -> TakeoverQueueItem:
        agent_id = _agent_id(thread_key)
        if not sender or not kind or not text:
            raise Invalid("queued chat sender, kind and text are required")
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_thread(db, thread_key)
            if request_id is not None:
                existing = db.execute(
                    "SELECT * FROM takeover_queue WHERE agent_id=? AND request_id=?",
                    (agent_id, request_id),
                ).fetchone()
                if existing:
                    return self._queue_item(existing)
            db.execute(
                "INSERT INTO takeover_queue(agent_id,sender,kind,text,queued_at,"
                "request_id) "
                "VALUES(?,?,?,?,?,?)",
                (agent_id, sender, kind, text, queued_at, request_id),
            )
            return self._queue_item(
                db.execute(
                    "SELECT * FROM takeover_queue WHERE id=last_insert_rowid()"
                ).fetchone()
            )

    def next_queued(self, thread_key: str) -> TakeoverQueueItem | None:
        agent_id = _agent_id(thread_key)
        with self._connection() as db:
            self._require_thread(db, thread_key)
            hold = db.execute(
                "SELECT released_at FROM takeover WHERE agent_id=?", (agent_id,)
            ).fetchone()
            if hold is not None and hold["released_at"] is None:
                return None
            row = db.execute(
                "SELECT * FROM takeover_queue WHERE agent_id=? "
                "AND delivered_at IS NULL "
                "AND dropped_reason IS NULL ORDER BY id LIMIT 1",
                (agent_id,),
            ).fetchone()
        return self._queue_item(row) if row else None

    def queued_count(self, thread_key: str) -> int:
        agent_id = _agent_id(thread_key)
        with self._connection() as db:
            self._require_thread(db, thread_key)
            row = db.execute(
                "SELECT count(*) FROM takeover_queue WHERE agent_id=? "
                "AND delivered_at IS NULL AND dropped_reason IS NULL",
                (agent_id,),
            ).fetchone()
        return int(row[0])

    def mark_delivered(
        self, thread_key: str, queue_id: int, send_outcome: str, delivered_at: str
    ) -> bool:
        if send_outcome != "SENT":
            raise Invalid("a queued chat row can be marked delivered only after SENT")
        agent_id = _agent_id(thread_key)
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_thread(db, thread_key)
            return (
                db.execute(
                    "UPDATE takeover_queue SET delivered_at=? "
                    "WHERE agent_id=? AND id=? "
                    "AND delivered_at IS NULL AND dropped_reason IS NULL",
                    (delivered_at, agent_id, queue_id),
                ).rowcount
                == 1
            )

    def drop(self, thread_key: str, queue_id: int, reason: str) -> bool:
        if not reason:
            raise Invalid("a dropped chat queue row requires a reason")
        agent_id = _agent_id(thread_key)
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_thread(db, thread_key)
            return (
                db.execute(
                    "UPDATE takeover_queue SET dropped_reason=? "
                    "WHERE agent_id=? AND id=? "
                    "AND delivered_at IS NULL AND dropped_reason IS NULL",
                    (reason, agent_id, queue_id),
                ).rowcount
                == 1
            )
