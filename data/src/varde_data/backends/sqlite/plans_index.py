"""Incremental, rebuildable SQLite index of file backed plans."""

from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from varde_core.frontmatter import parse
from varde_core.sqlite import configure_connection
from varde_data.backends.files.plans import FilesPlans
from varde_data.backends.sqlite.plans_index_schema import (
    SCHEMA,
    SCHEMA_VERSION,
    TABLE_KEYS,
)
from varde_data.errors import Invalid
from varde_data.records.plans import PlanRecord, TaskRecord

PLAN_ACTIVITY_REFRESH_SECONDS = 30.0


def _is_empty_index(db: sqlite3.Connection) -> bool:
    generation = db.execute("SELECT generation FROM meta").fetchone()
    plans = db.execute("SELECT EXISTS(SELECT 1 FROM plans)").fetchone()[0]
    return generation is None or (int(generation[0]) == 0 and not plans)


def _query_rows(
    db: sqlite3.Connection, query: str, values: tuple[object, ...] = ()
) -> list[dict[str, object]]:
    return [dict(row) for row in db.execute(query, values)]


def _is_corruption(error: sqlite3.DatabaseError) -> bool:
    if isinstance(error, sqlite3.OperationalError):
        return False
    message = str(error).lower()
    return "malformed" in message or "not a database" in message


def _replace_schema(db: sqlite3.Connection) -> None:
    tables = (*TABLE_KEYS, "meta")
    statements = [f'DROP TABLE IF EXISTS "{table}";' for table in tables]
    script = "BEGIN IMMEDIATE;\n" + "\n".join(statements) + SCHEMA
    script += f"UPDATE meta SET generation={time.time_ns()};\n"  # noqa: S608 - generated integer
    script += f"PRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;"
    db.executescript(script)


def _content_changed(
    changes: dict[str, tuple[list[dict[str, object]], set[str]]],
) -> bool:
    return any(
        rows or deleted
        for table, (rows, deleted) in changes.items()
        if table not in {"directories", "plan_activity"}
    )


class SqlitePlansIndex:
    """Maintain normalized plan rows while FilesPlans remains the parser."""

    def __init__(self, working: Path) -> None:
        self.working = Path(working)
        self.root = self.working / "plans"
        self.path = self.working / ".cache" / "plans-read-index.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._files = FilesPlans(self.working)
        self._table_snapshot: dict[str, dict[str, dict[str, object]]] | None = None
        self._snapshot_generation: int | None = None
        self._status_rows_generation: int | None = None
        self._status_rows_cache: dict[str, list[dict[str, object]]] | None = None
        self._status_rows_lock = threading.Lock()
        self._activity_refreshed_at: float | None = None
        if self._initialize():
            self.rebuild()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        configure_connection(db)
        return db

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as db, db:
            yield db

    @contextmanager
    def _writer_lock(self) -> Iterator[None]:
        with open(self.path.parent / ".plans-read-index.lock", "a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield

    def _initialize(self) -> bool:
        with self._writer_lock():
            try:
                with self._connection() as db:
                    version = db.execute("PRAGMA user_version").fetchone()[0]
                    if version > SCHEMA_VERSION:
                        raise Invalid(
                            f"plans index version {version} is newer than supported"
                        )
                    if version == SCHEMA_VERSION:
                        return _is_empty_index(db)
                    _replace_schema(db)
                    return True
            except sqlite3.DatabaseError as error:
                if not _is_corruption(error):
                    raise
                for suffix in ("", "-wal", "-shm"):
                    Path(f"{self.path}{suffix}").unlink(missing_ok=True)
        with self._writer_lock(), self._connection() as db:
            _replace_schema(db)
        return True

    def refresh(self) -> int:
        """Reconcile source files; return the resulting generation."""
        with self._writer_lock():
            generation = _read_generation(self)
            if (
                self._snapshot_generation == generation
                and self._table_snapshot is not None
            ):
                existing = self._table_snapshot
            else:
                existing, generation = _read_tables(self)
            directories, artifacts = self._snapshot(existing)
            source_unchanged = _source_stats_unchanged(
                self, existing, directories, artifacts
            )
            now = time.monotonic()
            activity_due = (
                self._activity_refreshed_at is None
                or now - self._activity_refreshed_at >= PLAN_ACTIVITY_REFRESH_SECONDS
            )
            if source_unchanged and not activity_due:
                self._table_snapshot = existing
                self._snapshot_generation = generation
                return generation
            current = _updated_tables(self, existing, directories, artifacts)
            if activity_due:
                activity_rows = _rows_by_key(
                    _plan_activity_rows(self.root, current["plans"]), "plan_path"
                )
                self._activity_refreshed_at = time.monotonic()
            else:
                activity_rows = {
                    path: row
                    for path, row in existing["plan_activity"].items()
                    if path in current["plans"]
                }
                for path, plan in current["plans"].items():
                    if path not in activity_rows:
                        mtime = plan.get("mtime_ns")
                        activity_rows[path] = {
                            "plan_path": path,
                            "newest_mtime_ns": mtime,
                            "latest_path": path,
                        }
            if source_unchanged and activity_rows == existing["plan_activity"]:
                self._table_snapshot = existing
                self._snapshot_generation = generation
                return generation
            current["plan_activity"] = activity_rows
            changes = _table_changes(existing, current)
            if all(not rows and not deleted for rows, deleted in changes.values()):
                self._table_snapshot = current
                self._snapshot_generation = generation
                return generation
            with self._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                _apply_changes(db, changes)
                if _content_changed(changes):
                    db.execute("UPDATE meta SET generation=generation+1")
                generation = db.execute("SELECT generation FROM meta").fetchone()[0]
            self._table_snapshot = current
            self._snapshot_generation = generation
            return generation

    def plan_rows(self) -> list[dict[str, object]]:
        """Return lightweight plan metadata without raw Markdown bytes."""
        return self._rows(
            'SELECT path,id,artifact_type,archived,status,title,label,"group",owner,'
            "assigned_to,branch,depends_on_json,merge_approved_at,frontmatter_json,"
            "purpose,open_questions,skipped_tasks,mtime_ns FROM plans ORDER BY path"
        )

    def task_rows(self, plan_path: str | None = None) -> list[dict[str, object]]:
        """Return lightweight task metadata, optionally for one plan."""
        query = (
            "SELECT path,plan_path,id,archived,status,status_at,depends_on_json,"
            "frontmatter_json,mtime_ns FROM tasks ORDER BY path"
        )
        if plan_path is None:
            return self._rows(query)
        return self._rows(
            query.replace(" ORDER BY path", " WHERE plan_path=? ORDER BY path"),
            (plan_path,),
        )

    def review_rows(self) -> list[dict[str, object]]:
        return self._rows("SELECT plan_path,verdict,reviewed_commit FROM reviews")

    def task_note_rows(self) -> list[dict[str, object]]:
        return self._rows("SELECT task_path,mtime_ns FROM task_notes")

    def now_line_rows(self) -> list[dict[str, object]]:
        return self._rows("SELECT plan_key,text,mtime_ns FROM now_lines")

    def invalid_rows(self) -> list[dict[str, object]]:
        return self._rows(
            "SELECT path,kind,artifact_kind,plan_path,archived FROM invalid_artifacts"
        )

    def activity_rows(self) -> list[dict[str, object]]:
        return self._rows(
            "SELECT plan_path,newest_mtime_ns,latest_path FROM plan_activity"
        )

    def status_rows(self) -> dict[str, list[dict[str, object]]]:
        with self._status_rows_lock:
            generation = self._snapshot_generation
            cached = self._status_rows_cache
            if cached is not None and self._status_rows_generation == generation:
                return {
                    name: [row.copy() for row in rows] for name, rows in cached.items()
                }
        with self._connection() as db:
            db.execute("BEGIN")
            rows = {
                "plans": _query_rows(
                    db,
                    'SELECT path,id,artifact_type,archived,status,title,label,"group",'
                    "owner,assigned_to,branch,depends_on_json,merge_approved_at,"
                    "group_json,shape,model,worktree,purpose,open_questions,"
                    "skipped_tasks,mtime_ns "
                    "FROM plans ORDER BY path",
                ),
                "tasks": _query_rows(
                    db,
                    "SELECT path,plan_path,id,archived,status,status_at,"
                    "depends_on_json,"
                    "title,mtime_ns FROM tasks ORDER BY path",
                ),
                "reviews": _query_rows(db, "SELECT plan_path,verdict FROM reviews"),
                "task_notes": _query_rows(
                    db, "SELECT task_path,mtime_ns FROM task_notes"
                ),
                "now_lines": _query_rows(
                    db, "SELECT plan_key,text,mtime_ns FROM now_lines"
                ),
                "invalid": _query_rows(
                    db,
                    "SELECT path,kind,artifact_kind,plan_path,archived "
                    "FROM invalid_artifacts",
                ),
            }
        with self._status_rows_lock:
            if generation == self._snapshot_generation:
                self._status_rows_generation = generation
                self._status_rows_cache = rows
        return {name: [row.copy() for row in values] for name, values in rows.items()}

    def watch_rows(self) -> dict[str, list[dict[str, object]]]:
        with self._connection() as db:
            db.execute("BEGIN")
            return {
                "plans": _query_rows(
                    db,
                    'SELECT path,id,artifact_type,archived,status,title,label,"group",'
                    "owner,assigned_to,branch,depends_on_json,merge_approved_at,"
                    "group_json,shape,model,worktree,purpose,open_questions,"
                    "skipped_tasks,mtime_ns "
                    "FROM plans WHERE archived=0 ORDER BY path",
                ),
                "tasks": _query_rows(
                    db,
                    "SELECT path,plan_path,id,archived,status,status_at,"
                    "depends_on_json,"
                    "title,mtime_ns FROM tasks WHERE archived=0 ORDER BY path",
                ),
                "now_lines": _query_rows(
                    db, "SELECT plan_key,text,mtime_ns FROM now_lines"
                ),
                "activity": _query_rows(
                    db,
                    "SELECT plan_path,newest_mtime_ns,latest_path FROM plan_activity",
                ),
            }

    def _rows(
        self, query: str, values: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        with self._connection() as db:
            return _query_rows(db, query, values)

    def _snapshot(
        self, existing: dict[str, dict[str, dict[str, object]]]
    ) -> tuple[list[dict[str, object]], dict[str, tuple[str, os.stat_result]]]:
        directory_rows, pending = _stat_directories(self.root, existing["directories"])
        changed_directories = set(map(str, pending))
        artifacts = _discover_changed(self._files, pending, directory_rows)
        artifacts.update(
            _stat_known_artifacts(existing, artifacts, changed_directories)
        )
        return list(directory_rows.values()), artifacts

    def rebuild(self) -> int:
        """Discard derived rows and repopulate them from the Markdown tree."""
        with self._writer_lock():
            _, generation = _read_tables(self)
            empty = {table: {} for table in TABLE_KEYS}
            directories, artifacts = self._snapshot(empty)
            current = _updated_tables(self, empty, directories, artifacts)
            current["plan_activity"] = _rows_by_key(
                _plan_activity_rows(self.root, current["plans"]), "plan_path"
            )
            self._activity_refreshed_at = time.monotonic()
            changes = _table_changes(empty, current)
            with self._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                for table in TABLE_KEYS:
                    db.execute(f'DELETE FROM "{table}"')  # noqa: S608 - fixed table names
                _apply_changes(db, changes)
                db.execute(
                    "UPDATE meta SET generation=?",
                    (max(generation + 1, time.time_ns()),),
                )
                generation = int(
                    db.execute("SELECT generation FROM meta").fetchone()[0]
                )
            self._table_snapshot = current
            self._snapshot_generation = generation
            return generation

    def generation(self) -> int:
        """Read the published index generation without scanning source files."""
        with self._connection() as db:
            row = db.execute("SELECT generation FROM meta").fetchone()
        return int(row[0]) if row is not None else 0


def _directory_row(path: Path, info: os.stat_result) -> dict[str, object]:
    return _directory_row_text(str(path), info)


def _directory_row_text(path: str, info: os.stat_result) -> dict[str, object]:
    return {
        "path": path,
        "dev": info.st_dev,
        "ino": info.st_ino,
        "mtime_ns": info.st_mtime_ns,
    }


def _rows_by_key(
    rows: list[dict[str, object]], key: str
) -> dict[str, dict[str, object]]:
    return {str(row[key]): row for row in rows}


def _plan_activity_rows(
    root: Path, plans: dict[str, dict[str, object]]
) -> list[dict[str, object]]:
    records = {Path(path).parent: path for path in plans}
    activity: dict[str, tuple[int, str]] = {}
    for directory, _, files in os.walk(root):
        parent = Path(directory)
        owners = _plan_owners(parent, records, root)
        if not owners:
            continue
        for filename in files:
            path = parent / filename
            try:
                modified = path.stat().st_mtime_ns
            except OSError:
                continue
            for owner in owners:
                old = activity.get(owner)
                if old is None or modified >= old[0]:
                    activity[owner] = (modified, str(path))
    return [
        {
            "plan_path": plan_path,
            "newest_mtime_ns": newest,
            "latest_path": path,
        }
        for plan_path, (newest, path) in activity.items()
    ]


def _plan_owners(directory: Path, records: dict[Path, str], root: Path) -> list[str]:
    current = directory
    owners = []
    while current.is_relative_to(root):
        owner = records.get(current)
        if owner is not None:
            owners.append(owner)
        if current == root:
            break
        current = current.parent
    return owners


def _stat_directories(
    root: Path, existing: dict[str, dict[str, object]]
) -> tuple[dict[str, dict[str, object]], list[Path]]:
    rows = {}
    changed = []
    paths = {str(root), *existing}
    stats = _stat_paths(paths)
    for path_text, info in stats.items():
        if info is None:
            continue
        row = _directory_row_text(path_text, info)
        rows[path_text] = row
        if existing.get(path_text) != row:
            changed.append(Path(path_text))
    return rows, changed


def _discover_changed(
    files: FilesPlans,
    pending: list[Path],
    directories: dict[str, dict[str, object]],
) -> dict[str, tuple[str, os.stat_result]]:
    artifacts = {}
    visited = set()
    while pending:
        directory = pending.pop()
        if str(directory) in visited:
            continue
        visited.add(str(directory))
        entries = files._index.paths(directory)
        if entries is None:
            continue
        has_plan = any(
            path.name == "plan.md" and is_file for path, _, is_file, _ in entries
        )
        for path, is_dir, is_file, is_symlink in entries:
            if is_dir:
                child_text = str(path)
                if child_text not in directories:
                    try:
                        row = _directory_row(path, path.stat())
                    except OSError:
                        continue
                    directories[child_text] = row
                    pending.append(path)
                continue
            if not (is_file or is_symlink):
                continue
            kind = _artifact_kind(path, directory, has_plan)
            if kind is None:
                continue
            try:
                artifacts[str(path)] = kind, path.stat()
            except OSError:
                continue
    return artifacts


def _stat_known_artifacts(
    existing: dict[str, dict[str, dict[str, object]]],
    already_statted: dict[str, tuple[str, os.stat_result]],
    changed_directories: set[str],
) -> dict[str, tuple[str, os.stat_result]]:
    known = {}
    for table, kind in (("plans", "plan"), ("tasks", "task")):
        for path_text in existing[table]:
            known[path_text] = kind
    for plan_path in existing["reviews"]:
        known[f"{plan_path.rsplit('/', 1)[0]}/review.md"] = "review"
    for path, row in existing["invalid_artifacts"].items():
        known[path] = str(row["artifact_kind"])
    for path in tuple(known):
        parent = str(Path(path).parent)
        if parent in changed_directories and path not in already_statted:
            known.pop(path)
    known = {path: kind for path, kind in known.items() if path not in already_statted}
    stats = _stat_paths(set(known))
    return {
        path: (kind, info)
        for path, kind in known.items()
        if (info := stats.get(path)) is not None
    }


def _stat_paths(paths: set[str]) -> dict[str, os.stat_result | None]:
    def stat(path: str) -> tuple[str, os.stat_result | None]:
        try:
            return path, os.stat(path)
        except OSError:
            return path, None

    return dict(stat(path) for path in paths)


def _artifact_kind(path: Path, directory: Path, has_plan: bool) -> str | None:
    if path.name == "review.md":
        return "review"
    if path.name == "plan.md":
        return "plan"
    if path.suffix == ".md" and directory.name == "tasks":
        return "task"
    if path.name == "task.md" and not has_plan:
        return "task"
    return None


def _read_tables(
    index: SqlitePlansIndex,
) -> tuple[dict[str, dict[str, dict[str, object]]], int]:
    columns = {
        "directories": ("path", "dev", "ino", "mtime_ns"),
        "plans": (
            "path",
            "artifact_type",
            "skipped_tasks",
            "mtime_ns",
            "ctime_ns",
            "size",
            "inode",
        ),
        "tasks": ("path", "id", "mtime_ns", "ctime_ns", "size", "inode"),
        "invalid_artifacts": (
            "path",
            "kind",
            "artifact_kind",
            "plan_path",
            "archived",
            "mtime_ns",
            "ctime_ns",
            "size",
            "inode",
        ),
        "reviews": (
            "plan_path",
            "verdict",
            "reviewed_commit",
            "mtime_ns",
            "ctime_ns",
            "size",
            "inode",
        ),
        "task_notes": ("task_path", "mtime_ns"),
        "now_lines": ("plan_key", "text", "mtime_ns"),
        "plan_activity": ("plan_path", "newest_mtime_ns", "latest_path"),
    }
    with index._connection() as db:
        tables = {
            table: {
                str(row[TABLE_KEYS[table]]): dict(row)
                for row in db.execute(
                    f'SELECT {",".join(column_set)} FROM "{table}"'  # noqa: S608 - fixed identifiers
                )
            }
            for table, column_set in columns.items()
        }
        generation = int(db.execute("SELECT generation FROM meta").fetchone()[0])
        return tables, generation


def _read_generation(index: SqlitePlansIndex) -> int:
    with index._connection() as db:
        return int(db.execute("SELECT generation FROM meta").fetchone()[0])


def _source_stats_unchanged(
    index: SqlitePlansIndex,
    existing: dict[str, dict[str, dict[str, object]]],
    directories: list[dict[str, object]],
    artifacts: dict[str, tuple[str, os.stat_result]],
) -> bool:
    if len(directories) != len(existing["directories"]):
        return False
    if any(existing["directories"].get(str(row["path"])) != row for row in directories):
        return False
    if not _artifact_stats_unchanged(existing, artifacts):
        return False
    return _notes_unchanged(existing) and _now_sources_unchanged(
        index, existing["now_lines"]
    )


def _artifact_stats_unchanged(
    existing: dict[str, dict[str, dict[str, object]]],
    artifacts: dict[str, tuple[str, os.stat_result]],
) -> bool:
    old_paths = set(existing["plans"]) | set(existing["tasks"])
    old_paths.update(
        f"{path.rsplit('/', 1)[0]}/review.md"
        for path, row in existing["reviews"].items()
        if row["mtime_ns"] is not None
    )
    old_paths.update(existing["invalid_artifacts"])
    if old_paths != set(artifacts):
        return False
    for path, (kind, info) in artifacts.items():
        invalid = existing["invalid_artifacts"].get(path)
        if invalid is not None:
            if _row_stat_key(invalid) != _stat_key(info):
                return False
            continue
        table = "plans" if kind == "plan" else "tasks" if kind == "task" else "reviews"
        row_path = path if table != "reviews" else f"{path.rsplit('/', 1)[0]}/plan.md"
        old = existing[table].get(row_path)
        if old is None or _row_stat_key(old) != _stat_key(info):
            return False
    return True


def _notes_unchanged(existing: dict[str, dict[str, dict[str, object]]]) -> bool:
    tasks = existing["tasks"]
    paths = {
        path: f"{path.rsplit('/', 2)[0]}/notes/{task['id']}.md"
        for path, task in tasks.items()
    }
    stats = _stat_paths(set(paths.values()))
    for path, row in existing["task_notes"].items():
        note = paths.get(path)
        if note is None:
            return False
        info = stats.get(note)
        if row["mtime_ns"] != (info.st_mtime_ns if info is not None else None):
            return False
    return True


def _now_sources_unchanged(
    index: SqlitePlansIndex, existing: dict[str, dict[str, object]]
) -> bool:
    paths = {}
    root = str(index.root.parent)
    for key in existing:
        paths[key] = (
            f"{root}/.cache/plan-now/{key}.txt",
            f"{root}/plan-now/{key}.txt",
        )
    stats = _stat_paths({path for values in paths.values() for path in values})
    for key, values in paths.items():
        old = existing[key]
        info = next((stats[path] for path in values if stats[path] is not None), None)
        mtime_ns = info.st_mtime_ns if info is not None else None
        if old["mtime_ns"] != mtime_ns:
            return False
    return True


def _updated_tables(
    index: SqlitePlansIndex,
    existing: dict[str, dict[str, dict[str, object]]],
    directories: list[dict[str, object]],
    artifacts: dict[str, tuple[str, os.stat_result]],
) -> dict[str, dict[str, dict[str, object]]]:
    current = {table: rows.copy() for table, rows in existing.items()}
    current["directories"] = {str(row["path"]): row for row in directories}
    current["invalid_artifacts"] = {}
    live_plans: set[str] = set()
    live_tasks: set[str] = set()
    live = {"plans": live_plans, "tasks": live_tasks}
    for path_text, (kind, info) in artifacts.items():
        _reconcile_artifact(
            index,
            current,
            existing,
            (path_text, (kind, info)),
            live,
        )

    current["plans"] = {
        path: row for path, row in current["plans"].items() if path in live_plans
    }
    current["tasks"] = {
        path: row for path, row in current["tasks"].items() if path in live_tasks
    }
    current["reviews"] = {
        path: row for path, row in current["reviews"].items() if path in live_plans
    }
    _update_skipped_task_counts(current)
    _update_reviews(index, current, live_plans, artifacts)

    current["task_notes"] = _task_note_rows(current["tasks"])
    current["now_lines"] = _now_rows(index, current["plans"], existing["now_lines"])
    return current


def _reconcile_artifact(
    index: SqlitePlansIndex,
    current: dict[str, dict[str, dict[str, object]]],
    existing: dict[str, dict[str, dict[str, object]]],
    artifact: tuple[str, tuple[str, os.stat_result]],
    live: dict[str, set[str]],
) -> None:
    path_text, (kind, info) = artifact
    if kind == "review":
        return
    old_invalid = existing["invalid_artifacts"].get(path_text)
    if old_invalid is not None and _row_stat_key(old_invalid) == _stat_key(info):
        current["invalid_artifacts"][path_text] = old_invalid
        return
    path = Path(path_text)
    old_table = "plans" if path_text in existing["plans"] else "tasks"
    old = existing[old_table].get(path_text)
    if old is not None and _row_stat_key(old) == _stat_key(info):
        table, row = old_table, old
    else:
        parsed = _document_row(index, path, kind, info)
        if parsed is None:
            _mark_invalid(index, current, path_text, path, kind, info)
            return
        table, row = parsed
    current["plans"].pop(path_text, None)
    current["tasks"].pop(path_text, None)
    current[table][path_text] = row
    live[table].add(path_text)


def _mark_invalid(
    index: SqlitePlansIndex,
    current: dict[str, dict[str, dict[str, object]]],
    path_text: str,
    path: Path,
    kind: str,
    info: os.stat_result,
) -> None:
    current["plans"].pop(path_text, None)
    current["tasks"].pop(path_text, None)
    current["invalid_artifacts"][path_text] = _invalid_artifact_row(
        index, path, kind, info
    )


def _update_skipped_task_counts(
    current: dict[str, dict[str, dict[str, object]]],
) -> None:
    skipped: dict[str, int] = {}
    for row in current["invalid_artifacts"].values():
        if row["kind"] != "task" or row["plan_path"] is None:
            continue
        path = str(row["plan_path"])
        skipped[path] = skipped.get(path, 0) + 1
    for path, row in current["plans"].items():
        count = skipped.get(path, 0)
        if row.get("skipped_tasks") != count:
            current["plans"][path] = {**row, "skipped_tasks": count}


def _update_reviews(
    index: SqlitePlansIndex,
    current: dict[str, dict[str, dict[str, object]]],
    live_plans: set[str],
    artifacts: dict[str, tuple[str, os.stat_result]],
) -> None:
    for plan_path in live_plans:
        review_path = Path(plan_path).parent / "review.md"
        review_artifact = artifacts.get(str(review_path))
        old = current["reviews"].get(plan_path)
        if review_artifact is None:
            current["reviews"][plan_path] = _empty_review_row(plan_path)
            continue
        if old is not None and _row_stat_key(old) == _stat_key(review_artifact[1]):
            continue
        current["reviews"][plan_path] = _review_row(
            index, review_path, plan_path, review_artifact[1]
        )


def _invalid_artifact_row(
    index: SqlitePlansIndex, path: Path, artifact_kind: str, info: os.stat_result
) -> dict[str, object]:
    task_folder = path.parent.name == "tasks"
    plan_path = path.parent.parent / "plan.md" if task_folder else None
    archived = "archive" in path.relative_to(index.root).parts[:-1]
    return {
        "path": str(path),
        "kind": "task" if task_folder else "document",
        "artifact_kind": artifact_kind,
        "plan_path": str(plan_path) if plan_path is not None else None,
        "archived": int(archived),
        **_stat_row(info),
    }


def _document_row(
    index: SqlitePlansIndex, path: Path, kind: str, info: os.stat_result
) -> tuple[str, dict[str, object]] | None:
    try:
        record = index._files._read_plan(
            path, "archive" in path.relative_to(index.root).parts[:-1]
        )
    except OSError, ValueError, UnicodeError:
        return None
    if record is None:
        return None
    if record.artifact_type == "task":
        if kind not in {"plan", "task"}:
            return None
        parent = path.parent.parent if path.parent.name == "tasks" else path.parent
        return "tasks", _task_row(
            record.path, parent / "plan.md", record, info, archived=record.archived
        )
    is_standalone_task_name = path.name == "task.md" and path.parent.name != "tasks"
    if record.artifact_type != "plan" or not (
        kind == "plan" or is_standalone_task_name
    ):
        return None
    body = _body_from_raw(record.raw)
    purpose, questions = _body_facts(body)
    fields = record.fields
    frontmatter_json, frontmatter_json_exact = _frontmatter_json(fields)
    return "plans", {
        "path": record.path,
        "id": record.id,
        "artifact_type": record.artifact_type,
        "archived": int(record.archived),
        "status": _text(fields.get("status")),
        "title": _text(fields.get("title")),
        "label": _text(fields.get("label")),
        "group": _text(fields.get("group")),
        "owner": fields.get("owner") if isinstance(fields.get("owner"), str) else None,
        "assigned_to": _text(fields.get("assigned_to")),
        "branch": _text(fields.get("branch")),
        "depends_on_json": json.dumps(fields.get("depends_on", []), sort_keys=True),
        "merge_approved_at": _text(fields.get("merge_approved_at")),
        "group_json": json.dumps(fields.get("group"), sort_keys=True, default=str),
        "shape": _text(fields.get("shape")),
        "model": _text(fields.get("model")),
        "worktree": _text(fields.get("worktree")),
        "frontmatter_json": frontmatter_json,
        "frontmatter_json_exact": frontmatter_json_exact,
        "purpose": purpose,
        "open_questions": questions,
        "skipped_tasks": 0,
        "raw": record.raw,
        **_stat_row(info),
    }


def _body_from_raw(raw: bytes) -> str:
    lines = raw.splitlines(keepends=True)
    delimiter = next(
        (
            offset
            for offset, line in enumerate(lines[1:], 1)
            if line.rstrip(b"\r\n") == b"---"
        ),
        None,
    )
    if delimiter is None:
        return ""
    return b"".join(lines[delimiter + 1 :]).decode("utf-8").lstrip("\r\n")


def _review_row(
    index: SqlitePlansIndex,
    path: Path,
    plan_path: str,
    info: os.stat_result,
) -> dict[str, object]:
    try:
        _, fields = index._files._index.fields(path, parse)
    except OSError, ValueError, UnicodeError:
        fields = {}
    return {
        "plan_path": plan_path,
        "verdict": _text(fields.get("verdict")),
        "reviewed_commit": _text(fields.get("reviewed_commit")),
        **_stat_row(info),
    }


def _empty_review_row(plan_path: str) -> dict[str, object]:
    return {
        "plan_path": plan_path,
        "verdict": None,
        "reviewed_commit": None,
        "mtime_ns": None,
        "ctime_ns": None,
        "size": None,
        "inode": None,
    }


def _task_note_rows(
    tasks: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    notes = {
        path: Path(path).parent.parent / "notes" / f"{task['id']}.md"
        for path, task in tasks.items()
    }
    stats = _stat_paths({str(note) for note in notes.values()})
    rows = {}
    for path, note in notes.items():
        info = stats.get(str(note))
        mtime_ns = info.st_mtime_ns if info is not None else None
        rows[path] = {"task_path": path, "mtime_ns": mtime_ns}
    return rows


def _now_rows(
    index: SqlitePlansIndex,
    plans: dict[str, dict[str, object]],
    existing: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    locations = {}
    for path in plans:
        directory = Path(path).parent
        key = "__".join(
            part.replace("_", "_u") for part in directory.relative_to(index.root).parts
        )
        locations[key] = (
            index.root.parent / ".cache" / "plan-now" / f"{key}.txt",
            index.root.parent / "plan-now" / f"{key}.txt",
        )
    stats = _stat_paths(
        {
            str(candidate)
            for candidates in locations.values()
            for candidate in candidates
        }
    )
    rows = {}
    for key, candidates in locations.items():
        old = existing.get(key)
        text = None
        mtime_ns = None
        for candidate in candidates:
            info = stats.get(str(candidate))
            if info is None:
                continue
            mtime_ns = info.st_mtime_ns
            if old is not None and old["mtime_ns"] == mtime_ns:
                text = old["text"]
            else:
                try:
                    lines = candidate.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                text = lines[0].strip() if lines else ""
            break
        rows[key] = {"plan_key": key, "text": text or None, "mtime_ns": mtime_ns}
    return rows


def _task_row(
    path: str,
    plan_path: Path | str,
    task: TaskRecord | PlanRecord,
    info: os.stat_result,
    *,
    archived: bool,
) -> dict[str, object]:
    fields = task.fields
    frontmatter_json, frontmatter_json_exact = _frontmatter_json(fields)
    return {
        "path": path,
        "plan_path": str(plan_path),
        "id": task.id,
        "archived": int(archived),
        "status": _text(fields.get("status")),
        "status_at": _text(fields.get("status_at")),
        "title": _text(fields.get("title")),
        "depends_on_json": json.dumps(fields.get("depends_on", []), sort_keys=True),
        "frontmatter_json": frontmatter_json,
        "frontmatter_json_exact": frontmatter_json_exact,
        "raw": task.raw,
        **_stat_row(info),
    }


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _frontmatter_json(fields: dict[str, object]) -> tuple[str, int]:
    try:
        encoded = json.dumps(fields, sort_keys=True, default=str)
    except TypeError, ValueError:
        return "{}", 0
    return encoded, int(json.loads(encoded) == fields)


def _body_facts(body: str) -> tuple[str, str]:
    match = re.search(r"(?ims)^##\s+Problem\s*\n(.*?)(?=^##\s+|\Z)", body)
    paragraph = re.sub(r"\s+", " ", match.group(1)).strip() if match else ""
    sentence = re.split(r"(?<=[.!?])\s+", paragraph, maxsplit=1)[0]
    purpose = (
        sentence
        if len(sentence) <= 140
        else sentence[: max(1, sentence[:140].rfind(" "))].rstrip() + "…"
    )
    section = re.search(r"(?ims)^##\s+Open questions\s*\n(.*?)(?=^##\s+|\Z)", body)
    questions = section.group(1).strip() if section else ""
    return purpose, questions


def _stat_row(info: os.stat_result) -> dict[str, int | None]:
    if time.time_ns() - info.st_mtime_ns < 2_000_000_000:
        return {
            "mtime_ns": info.st_mtime_ns,
            "ctime_ns": None,
            "size": None,
            "inode": None,
        }
    return {
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
        "size": info.st_size,
        "inode": info.st_ino,
    }


def _stat_key(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_mtime_ns, info.st_ctime_ns, info.st_size, info.st_ino)


def _row_stat_key(row: dict[str, object]) -> tuple[int, int, int, int] | None:
    values = (
        row.get("mtime_ns"),
        row.get("ctime_ns"),
        row.get("size"),
        row.get("inode"),
    )
    if any(not isinstance(value, int) for value in values):
        return None
    mtime, ctime, size, inode = values
    if not isinstance(mtime, int) or not isinstance(ctime, int):
        return None
    if not isinstance(size, int) or not isinstance(inode, int):
        return None
    return mtime, ctime, size, inode


def _table_changes(
    existing: dict[str, dict[str, dict[str, object]]],
    current: dict[str, dict[str, dict[str, object]]],
) -> dict[str, tuple[list[dict[str, object]], set[str]]]:
    changes = {}
    for table in TABLE_KEYS:
        rows = current[table]
        previous = existing[table]
        changed = [row for path, row in rows.items() if previous.get(path) != row]
        deleted = previous.keys() - rows.keys()
        changes[table] = changed, set(deleted)
    return changes


def _apply_changes(
    db: sqlite3.Connection,
    changes: dict[str, tuple[list[dict[str, object]], set[str]]],
) -> None:
    for table, (rows, deleted) in changes.items():
        key = TABLE_KEYS[table]
        for value in deleted:
            db.execute(
                f'DELETE FROM "{table}" WHERE "{key}"=?',  # noqa: S608 - fixed names
                (value,),
            )
        _replace_rows(db, table, key, rows)


def _replace_rows(
    db: sqlite3.Connection, table: str, key: str, rows: list[dict[str, object]]
) -> None:
    for row in rows:
        columns = tuple(row)
        names = ",".join(f'"{column}"' for column in columns)
        values = ",".join("?" for _ in columns)
        updates = ",".join(
            f'"{column}"=excluded."{column}"' for column in columns if column != key
        )
        statement = (
            f'INSERT INTO "{table}" ({names}) VALUES ({values}) '  # noqa: S608 - fixed identifiers
            f'ON CONFLICT("{key}") DO UPDATE SET {updates}'
        )
        db.execute(
            statement,
            tuple(row[column] for column in columns),
        )
