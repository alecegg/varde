"""Build small historical DecisionStore databases for migration tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "decisions"


def build(path: Path, *, record_json: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        record_column = (
            ", record_json TEXT NOT NULL DEFAULT '{}'" if record_json else ""
        )
        db.executescript(
            f"""CREATE TABLE decisions (
                decision_id TEXT PRIMARY KEY, state TEXT NOT NULL,
                source_msg_ids TEXT NOT NULL DEFAULT '[]', answer_key TEXT,
                kind TEXT NOT NULL DEFAULT 'agent_question'{record_column});
            CREATE TABLE answers (
                entry_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL,
                idempotency_key TEXT UNIQUE NOT NULL, recipient TEXT NOT NULL,
                body BLOB NOT NULL, status TEXT NOT NULL, notes_path TEXT NOT NULL,
                delivery_msg_id TEXT);
            CREATE TABLE audit (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, decision_id TEXT NOT NULL,
                prior_state TEXT NOT NULL, new_state TEXT NOT NULL,
                actor TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL,
                msg_ids TEXT NOT NULL);
            """
        )
        decisions = [
            (
                "decision-stored",
                "answered",
                '["source-stored"]',
                "key-stored",
                "agent_question",
            ),
            (
                "decision-sending",
                "answered",
                '["source-sending"]',
                "key-sending",
                "question",
            ),
            (
                "decision-delivered",
                "answered",
                '["source-delivered"]',
                "key-delivered",
                "approval",
            ),
            (
                "decision-failed",
                "pending",
                '["source-failed"]',
                None,
                "permission",
            ),
        ]
        for decision_id, state, sources, key, kind in decisions:
            values = (decision_id, state, sources, key, kind)
            if record_json:
                values += ('{"context":{},"title":"Fixture"}',)
                db.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?)", values)
            else:
                db.execute("INSERT INTO decisions VALUES (?,?,?,?,?)", values)
        for status, decision_id, key in zip(
            ("stored", "sending", "delivered", "failed"),
            (
                "decision-stored",
                "decision-sending",
                "decision-delivered",
                "decision-failed",
            ),
            ("key-stored", "key-sending", "key-delivered", "key-failed"),
            strict=True,
        ):
            db.execute(
                "INSERT INTO answers VALUES (?,?,?,?,?,?,?,?)",
                (
                    f"entry-{status}",
                    decision_id,
                    key,
                    "fixture-agent",
                    status.encode(),
                    status,
                    f"/fixture-root/notes/{status}.md",
                    f"msg-{status}" if status == "delivered" else None,
                ),
            )
        audit_rows = [
            (
                "decision-stored",
                "pending",
                "answered",
                "answer stored",
                '["source-stored"]',
            ),
            (
                "decision-delivered",
                "sending",
                "delivered",
                "answer delivered",
                '["msg-delivered"]',
            ),
            (
                "decision-failed",
                "answered",
                "pending",
                "delivery failed",
                '["source-failed"]',
            ),
            (
                "decision-delivered",
                "delivered",
                "plan-write-failed",
                "entry-delivered: plan answer write-back failed: fixture",
                '["source-delivered"]',
            ),
        ]
        for decision_id, prior, current, reason, msg_ids in audit_rows:
            db.execute(
                "INSERT INTO audit(decision_id,prior_state,new_state,actor,at,"
                "reason,msg_ids) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    decision_id,
                    prior,
                    current,
                    "user",
                    "2026-10-22T00:00:00+00:00",
                    reason,
                    msg_ids,
                ),
            )
        db.execute(
            "INSERT INTO audit(decision_id,prior_state,new_state,actor,at,reason,"
            "msg_ids) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                "decision-delivered",
                "delivered",
                "plan-write-failed",
                "user",
                "2026-10-22T00:00:00+00:00",
                "entry-delivered: plan answer write-back failed: fixture",
                '["source-delivered"]',
            ),
        )


if __name__ == "__main__":
    build(FIXTURES / "v0_no_record_json.sqlite3", record_json=False)
    build(FIXTURES / "v0_current.sqlite3", record_json=True)
