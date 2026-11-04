"""Merge approval records from the user, main agent, or in-process guard.

Append-only (triggers refuse update and delete). `varde plan merge`, the
pre-merge-commit check and `varde plan merged` read the latest row per plan.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from varde_core.sqlite import configure_connection


@dataclass(frozen=True, slots=True)
class MergeApproval:
    id: int
    plan_id: str
    approved_by: str
    approved_at: str
    note: str | None
    approver_kind: str = "user"
    checklist: dict[str, object] | None = None
    key_kind: str = "plan"
    commit_sha: str | None = None


# Keep aligned with workflow.merge_approval.parse_approval's trusted fields.
CHECKLIST_FIELDS = ("plan_followed", "review_commit", "gate_result", "abnormal_events")


def validate_agent_checklist(checklist: object, reviewed_commit: str) -> str | None:
    if not isinstance(checklist, dict):
        return "checklist is required"
    if any(field not in checklist for field in CHECKLIST_FIELDS):
        return (
            "checklist must include plan_followed, review_commit, gate_result, "
            "and abnormal_events"
        )
    if checklist.get("plan_followed") is not True:
        return "checklist plan_followed must be true"
    if not all(
        isinstance(checklist.get(field), str) and checklist[field].strip()
        for field in CHECKLIST_FIELDS[1:]
    ):
        return "checklist text fields must be non-empty"
    if str(checklist.get("gate_result", "")).strip().lower() not in {"pass", "passed"}:
        return "checklist gate_result must be pass"
    if not reviewed_commit or checklist.get("review_commit") != reviewed_commit:
        return "checklist review_commit must match the plan's non-empty reviewed_commit"
    return None


class MergeApprovals:
    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / ".cache" / "dashboard" / "merge-approvals.sqlite3"
        self._lock = threading.Lock()
        with self._connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS merge_approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    approved_at TEXT NOT NULL,
                    note TEXT,
                    approver_kind TEXT NOT NULL DEFAULT 'user',
                    checklist TEXT,
                    key_kind TEXT NOT NULL DEFAULT 'plan',
                    commit_sha TEXT
                );
                CREATE INDEX IF NOT EXISTS merge_approvals_plan
                    ON merge_approvals(plan_id, id);
                CREATE TRIGGER IF NOT EXISTS merge_approvals_no_update
                    BEFORE UPDATE ON merge_approvals
                    BEGIN SELECT RAISE(ABORT, 'merge_approvals is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS merge_approvals_no_delete
                    BEFORE DELETE ON merge_approvals
                    BEGIN SELECT RAISE(ABORT, 'merge_approvals is append-only'); END;
                """
            )
            columns = {
                row["name"] for row in db.execute("PRAGMA table_info(merge_approvals)")
            }
            for name, definition in (
                ("approver_kind", "TEXT NOT NULL DEFAULT 'user'"),
                ("checklist", "TEXT"),
                ("key_kind", "TEXT NOT NULL DEFAULT 'plan'"),
                ("commit_sha", "TEXT"),
            ):
                if name not in columns:
                    db.execute(
                        f"ALTER TABLE merge_approvals ADD COLUMN {name} {definition}"
                    )

    @contextmanager
    def _connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        configure_connection(db)
        with closing(db), db:
            yield db

    def record(  # noqa: PLR0913 - record has a fixed persisted field set.
        self,
        plan_id: str,
        approved_by: str,
        note: str | None,
        *,
        approver_kind: str = "user",
        checklist: dict[str, object] | None = None,
        key_kind: str = "plan",
        commit_sha: str | None = None,
    ) -> MergeApproval:
        stamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        with self._lock, self._connection() as db:
            cursor = db.execute(
                "INSERT INTO merge_approvals("
                "plan_id, approved_by, approved_at, note, approver_kind, "
                "checklist, key_kind, commit_sha)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plan_id,
                    approved_by,
                    stamp,
                    note,
                    approver_kind,
                    json.dumps(checklist) if checklist is not None else None,
                    key_kind,
                    commit_sha,
                ),
            )
            return MergeApproval(
                int(cursor.lastrowid or 0),
                plan_id,
                approved_by,
                stamp,
                note,
                approver_kind,
                checklist,
                key_kind,
                commit_sha,
            )

    def latest(self, plan_id: str) -> MergeApproval | None:
        with self._lock, self._connection() as db:
            row = db.execute(
                "SELECT * FROM merge_approvals WHERE plan_id = ? ORDER BY id DESC"
                " LIMIT 1",
                (plan_id,),
            ).fetchone()
        if not row:
            return None
        record = dict(row)
        record["checklist"] = (
            json.loads(record["checklist"]) if record["checklist"] else None
        )
        return MergeApproval(**record)

    def record_guard(
        self,
        plan_id: str,
        checklist: dict[str, object],
        reviewed_commit: str,
        note: str | None = None,
    ) -> MergeApproval:
        error = validate_agent_checklist(checklist, reviewed_commit)
        if error:
            raise ValueError(error)
        key_kind = "branch" if plan_id.startswith("branch:") else "plan"
        return self.record(
            plan_id,
            "guard",
            note,
            approver_kind="guard",
            checklist=checklist,
            key_kind=key_kind,
            commit_sha=reviewed_commit,
        )
