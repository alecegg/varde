"""Role inbox facade for shared message streams and holder cursors."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from varde_data.backends.sqlite.messages import SQLiteMessages
from varde_data.errors import Invalid, NotFound
from varde_data.records.messages import Message, NewMessage
from varde_data.repos.messages import validate_address
from varde_data.roles import ROLES, role_for_address


def _now_stamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def select_role_inbox(working: Path) -> RoleInbox | None:
    """Select the shared inbox only when SQLite is the active mail store."""
    from varde_data.store_mode import read_store_mode

    mode = read_store_mode(working)
    if mode is None or mode.primary != "sqlite" or mode.mirror != "none":
        return None
    return open_role_inbox(working)


def role_key_for_selector(address: str) -> str | None:
    """Map an explicit role selector to its shared stream key."""
    if address in {"main", "manager"}:
        return "main"
    role, separator, qualifier = address.partition(":")
    if role not in ROLES or (separator and not qualifier):
        return None
    return role if not separator else f"{role}:{qualifier}"


def role_keys_for_holder(holder: str) -> tuple[str, ...]:
    """Return the specific and unqualified streams served by a holder."""
    selector = role_key_for_selector(holder)
    if selector is not None:
        role = selector.partition(":")[0]
        return (selector,) if selector == role else (selector, role)
    role = role_for_address(holder)
    if role is None:
        return ()
    if role == "orchestrator":
        qualifier = holder.removeprefix("orchestrator-")
    else:
        qualifier = holder[: -(len(role) + 1)]
    specific = f"{role}:{qualifier}" if qualifier else role
    return (specific, role) if qualifier else (specific,)


def role_matches_holder(role_key: str, holder: str) -> bool:
    """Whether a holder belongs to a role stream, including an unqualified one."""
    keys = role_keys_for_holder(holder)
    return role_key in keys


if TYPE_CHECKING:
    from varde_data.repos.queue import QueueRepository
    from varde_data.repos.slots import SlotRepository


class RoleInbox:
    """Expose shared role mail with independent per-holder read positions."""

    def __init__(self, repository: SQLiteMessages, working: Path) -> None:
        self._repository = repository
        self._working = working

    def queue(self) -> QueueRepository:
        """Open this inbox's work-item stream."""
        from varde_data.queue import open_queue

        return open_queue(self._working)

    def slots(self) -> SlotRepository:
        """Open claims, leases, and fencing for this inbox's work items."""
        from varde_data.queue import open_slots

        return open_slots(self._working)

    @staticmethod
    def role_key(role: str, qualifier: str | None = None) -> str:
        """Format and validate a role key with an optional qualifier."""
        if not role or ":" in role or (qualifier is not None and not qualifier):
            raise Invalid("role inbox key is invalid")
        key = role if qualifier is None else f"{role}:{qualifier}"
        validate_address(key, "role")
        return key

    def append(self, role_key: str, message: NewMessage) -> Message:
        """Append a single message addressed to the role stream."""
        return self._repository.append(
            NewMessage(
                message.from_,
                role_key,
                message.kind,
                message.text,
                message.notes,
                message.ts,
                message.reply_to,
            )
        )

    def unread(self, role_key: str, holder: str) -> tuple[Message, ...]:
        validate_address(role_key, "role")
        with self._repository._connection() as db:
            cursor = db.execute(
                "SELECT cursor_seq FROM role_holder_cursors "
                "WHERE role_key=? AND holder=?",
                (role_key, holder),
            ).fetchone()
            if cursor is None:
                raise NotFound("role holder is not registered")
            rows = db.execute(
                "SELECT m.* FROM messages AS m WHERE m.recipient=? AND m.seq>? "
                "AND NOT EXISTS (SELECT 1 FROM deliveries AS d "
                "WHERE d.message_id=m.id AND d.reader IN (?,?) "
                "AND d.event IN ('delivered','dropped','legacy','acked')) "
                "ORDER BY m.seq",
                (role_key, cursor["cursor_seq"], holder, role_key),
            ).fetchall()
        return tuple(self._repository._message(row) for row in rows)

    def claim_unread(
        self, role_key: str, holder: str, *, now: str, via: str = "cli"
    ) -> tuple[Message, ...]:
        """Read role mail and record delivery plus acknowledgement for its holder."""
        validate_address(role_key, "role")
        with self._repository._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "SELECT cursor_seq FROM role_holder_cursors "
                "WHERE role_key=? AND holder=?",
                (role_key, holder),
            ).fetchone()
            if cursor is None:
                raise NotFound("role holder is not registered")
            rows = db.execute(
                "SELECT m.* FROM messages AS m WHERE m.recipient=? AND m.seq>? "
                "AND NOT EXISTS (SELECT 1 FROM deliveries AS d "
                "WHERE d.message_id=m.id AND d.reader IN (?,?) "
                "AND d.event IN ('delivered','dropped','legacy','acked')) "
                "ORDER BY m.seq",
                (role_key, cursor["cursor_seq"], holder, role_key),
            ).fetchall()
            for row in rows:
                self._record_read_events(db, row["id"], holder, via, now)
            if rows:
                db.execute(
                    "UPDATE role_holder_cursors SET cursor_seq=MAX(cursor_seq,?) "
                    "WHERE role_key=? AND holder=?",
                    (rows[-1]["seq"], role_key, holder),
                )
                self._repository._bump(db)
        return tuple(self._repository._message(row) for row in rows)

    @staticmethod
    def _record_read_events(db, message_id: str, holder: str, via: str, now: str):
        for event in ("delivered", "acked"):
            exists = db.execute(
                "SELECT 1 FROM deliveries WHERE message_id=? AND reader=? AND event=?",
                (message_id, holder, event),
            ).fetchone()
            if exists is None:
                db.execute(
                    "INSERT INTO deliveries(message_id,reader,session,via,event,at) "
                    "VALUES(?,?,'',?,?,?)",
                    (message_id, holder, via, event, now),
                )

    def advance(self, role_key: str, holder: str, cursor_seq: int) -> None:
        validate_address(role_key, "role")
        if cursor_seq < 0:
            raise Invalid("role cursor cannot be negative")
        with self._repository._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            head = db.execute(
                "SELECT COALESCE(MAX(seq),0) FROM messages WHERE recipient=?",
                (role_key,),
            ).fetchone()[0]
            if cursor_seq > head:
                raise Invalid("role cursor is outside the stream")
            updated = db.execute(
                "UPDATE role_holder_cursors SET cursor_seq=MAX(cursor_seq,?) "
                "WHERE role_key=? AND holder=?",
                (cursor_seq, role_key, holder),
            ).rowcount
            if not updated:
                raise NotFound("role holder is not registered")

    def ack(self, role_key: str, holder: str, message_id: str) -> None:
        validate_address(role_key, "role")
        with self._repository._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT seq FROM messages WHERE id=? AND recipient=?",
                (message_id, role_key),
            ).fetchone()
            if row is None:
                raise NotFound("message does not exist in this role inbox")
            updated = db.execute(
                "UPDATE role_holder_cursors SET cursor_seq=MAX(cursor_seq,?) "
                "WHERE role_key=? AND holder=?",
                (row["seq"], role_key, holder),
            ).rowcount
            if not updated:
                raise NotFound("role holder is not registered")
            self._record_read_events(db, message_id, holder, "cli", _now_stamp())
            self._repository._bump(db)

    def add_holder(
        self,
        role_key: str,
        holder: str,
        *,
        inherit_from: str | None = None,
        live_holders: tuple[str, ...] | None = None,
    ) -> None:
        self.add_holders(
            role_key,
            (holder,),
            inherit_from=inherit_from,
            live_holders=live_holders,
        )

    def add_holders(
        self,
        role_key: str,
        holders: tuple[str, ...],
        *,
        inherit_from: str | None = None,
        live_holders: tuple[str, ...] | None = None,
    ) -> None:
        """Register new holders without replaying prior role mail."""
        validate_address(role_key, "role")
        if not holders or any(not holder for holder in holders):
            raise Invalid("role and holder are required")
        with self._repository._connection() as db:
            existing = {
                row["holder"]: row["cursor_seq"]
                for row in db.execute(
                    "SELECT holder,cursor_seq FROM role_holder_cursors "
                    "WHERE role_key=?",
                    (role_key,),
                )
            }
            if set(holders) <= set(existing):
                return
            db.execute("BEGIN IMMEDIATE")
            existing = {
                row["holder"]: row["cursor_seq"]
                for row in db.execute(
                    "SELECT holder,cursor_seq FROM role_holder_cursors "
                    "WHERE role_key=?",
                    (role_key,),
                )
            }
            if inherit_from is None:
                live = set(existing) if live_holders is None else set(live_holders)
                has_live_holder = bool(set(existing) & live)
                if has_live_holder:
                    cursor = db.execute(
                        "SELECT COALESCE(MAX(seq),0) FROM messages WHERE recipient=?",
                        (role_key,),
                    ).fetchone()[0]
                elif existing:
                    cursor = min(existing.values())
                else:
                    cursor = 0
            else:
                predecessor = db.execute(
                    "SELECT cursor_seq FROM role_holder_cursors "
                    "WHERE role_key=? AND holder=?",
                    (role_key, inherit_from),
                ).fetchone()
                if predecessor is None:
                    raise NotFound("predecessor role holder is not registered")
                cursor = predecessor["cursor_seq"]
            added = 0
            for holder in holders:
                if holder in existing:
                    continue
                db.execute(
                    "INSERT INTO role_holder_cursors VALUES (?,?,?)",
                    (role_key, holder, cursor),
                )
                added += 1
            if added:
                self._repository._bump(db)

    def remove_holder(self, role_key: str, holder: str) -> bool:
        validate_address(role_key, "role")
        with self._repository._connection() as db:
            return (
                db.execute(
                    "DELETE FROM role_holder_cursors WHERE role_key=? AND holder=?",
                    (role_key, holder),
                ).rowcount
                > 0
            )


def open_role_inbox(working: Path) -> RoleInbox:
    """Open the SQLite role inbox for a working directory."""
    from varde_data.backends.sqlite.messages import messages_db_path

    return RoleInbox(SQLiteMessages(messages_db_path(working)), working)
