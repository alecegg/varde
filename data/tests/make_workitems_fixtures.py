"""Build small historical work-item SQLite databases for migration tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "workitems"


def build(
    path: Path, *, answer_key: bool, launch_request: bool, wal: bool = False
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    if wal:
        db.execute("PRAGMA journal_mode=WAL")
    launch_columns = (
        ", launch_request_id TEXT, launch_request_notes TEXT" if launch_request else ""
    )
    answer_column = ", answer_key TEXT" if answer_key else ""
    db.executescript(
        f"""CREATE TABLE work_items (
            id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
            text TEXT NOT NULL, project TEXT NOT NULL, state TEXT NOT NULL,
            notes_path TEXT NOT NULL, planner_session TEXT, plan_path TEXT,
            plan_ready_id TEXT{launch_columns});
        CREATE TABLE work_item_audit (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL,
            prior_state TEXT, new_state TEXT NOT NULL, detail TEXT NOT NULL);
        CREATE TABLE work_item_questions (
            item_id TEXT NOT NULL, msg_id TEXT NOT NULL, payload TEXT NOT NULL,
            answer TEXT{answer_column}, PRIMARY KEY(item_id, msg_id));"""
    )
    fields = (
        "id,idempotency_key,text,project,state,"
        "notes_path,planner_session,plan_path,plan_ready_id"
    )
    values = [
        (
            "item-new",
            "key-new",
            "A new request",
            "workspace",
            "new",
            "/notes/item-new/request.md",
            None,
            None,
            None,
        ),
        (
            "item-planning",
            "key-planning",
            "Planning request",
            "workspace",
            "planning",
            "/notes/item-planning/request.md",
            "planner-1",
            None,
            None,
        ),
        (
            "item-queued",
            "key-queued",
            "Queued request",
            "dashboard-test",
            "queued",
            "/notes/item-queued/request.md",
            "planner-2",
            "/plans/example.md",
            "ready-message",
        ),
    ]
    if launch_request:
        fields += ",launch_request_id,launch_request_notes"
        values = [row + (None, None) for row in values]
        values[-1] = values[-1][:-2] + ("sending", "/notes/launch-request.md")
    db.executemany(
        f"INSERT INTO work_items({fields}) VALUES({','.join('?' for _ in values[0])})",
        values,
    )
    db.executemany(
        "INSERT INTO work_item_questions(item_id,msg_id,payload,answer"
        + (",answer_key" if answer_key else "")
        + ") VALUES("
        + ",".join("?" for _ in range(5 if answer_key else 4))
        + ")",
        [
            ("item-planning", "question-1", '{"asked":"Which target?"}', None, None)
            if answer_key
            else ("item-planning", "question-1", '{"asked":"Which target?"}', None),
            (
                "item-queued",
                "question-2",
                '{"asked":"Confirm launch?"}',
                "Yes",
                "answer-2",
            )
            if answer_key
            else ("item-queued", "question-2", '{"asked":"Confirm launch?"}', "Yes"),
        ],
    )
    db.executemany(
        "INSERT INTO work_item_audit(item_id,prior_state,new_state,detail) "
        "VALUES(?,?,?,?)",
        [
            ("item-new", None, "new", "submitted"),
            ("item-planning", None, "new", "submitted"),
            ("item-planning", "new", "planning", "planner started"),
            ("item-queued", None, "new", "submitted"),
            ("item-queued", "new", "planning", "planner started"),
            ("item-queued", "planning", "ready", "plan ready"),
            ("item-queued", "ready", "queued", "user decision"),
        ],
    )
    db.commit()
    db.close()


if __name__ == "__main__":
    build(FIXTURES / "v0_oldest.sqlite3", answer_key=False, launch_request=False)
    build(FIXTURES / "v0_answer_key.sqlite3", answer_key=True, launch_request=False)
    build(FIXTURES / "v0_current.sqlite3", answer_key=True, launch_request=True)
    build(
        FIXTURES / "v0_current_wal.sqlite3",
        answer_key=True,
        launch_request=True,
        wal=True,
    )
