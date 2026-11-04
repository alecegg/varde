"""Schema for the rebuildable plans read index."""

SCHEMA_VERSION = 6

TABLE_KEYS = {
    "directories": "path",
    "plans": "path",
    "tasks": "path",
    "invalid_artifacts": "path",
    "reviews": "plan_path",
    "task_notes": "task_path",
    "now_lines": "plan_key",
    "plan_activity": "plan_path",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS directories (
    path TEXT PRIMARY KEY, dev INTEGER NOT NULL, ino INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    path TEXT PRIMARY KEY, id TEXT NOT NULL, artifact_type TEXT NOT NULL,
    archived INTEGER NOT NULL, status TEXT, title TEXT, label TEXT, "group" TEXT,
    owner TEXT, assigned_to TEXT, branch TEXT, depends_on_json TEXT,
    merge_approved_at TEXT, frontmatter_json TEXT NOT NULL,
    group_json TEXT NOT NULL, shape TEXT, model TEXT, worktree TEXT,
    frontmatter_json_exact INTEGER NOT NULL, purpose TEXT,
    open_questions TEXT, skipped_tasks INTEGER NOT NULL,
    mtime_ns INTEGER, ctime_ns INTEGER,
    size INTEGER, inode INTEGER, raw BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    path TEXT PRIMARY KEY, plan_path TEXT NOT NULL, id TEXT NOT NULL,
    archived INTEGER NOT NULL,
    status TEXT, status_at TEXT, title TEXT, depends_on_json TEXT,
    frontmatter_json TEXT NOT NULL, frontmatter_json_exact INTEGER NOT NULL,
    mtime_ns INTEGER,
    ctime_ns INTEGER, size INTEGER, inode INTEGER,
    raw BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS invalid_artifacts (
    path TEXT PRIMARY KEY, kind TEXT NOT NULL, artifact_kind TEXT NOT NULL,
    plan_path TEXT,
    archived INTEGER NOT NULL, mtime_ns INTEGER,
    ctime_ns INTEGER, size INTEGER, inode INTEGER
);
CREATE TABLE IF NOT EXISTS reviews (
    plan_path TEXT PRIMARY KEY, verdict TEXT, reviewed_commit TEXT,
    mtime_ns INTEGER, ctime_ns INTEGER, size INTEGER, inode INTEGER
);
CREATE TABLE IF NOT EXISTS task_notes (
    task_path TEXT PRIMARY KEY, mtime_ns INTEGER
);
CREATE TABLE IF NOT EXISTS now_lines (
    plan_key TEXT PRIMARY KEY, text TEXT, mtime_ns INTEGER
);
CREATE TABLE IF NOT EXISTS plan_activity (
    plan_path TEXT PRIMARY KEY, newest_mtime_ns INTEGER, latest_path TEXT
);
CREATE TABLE IF NOT EXISTS meta (generation INTEGER NOT NULL);
INSERT INTO meta(generation) SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM meta);
"""
