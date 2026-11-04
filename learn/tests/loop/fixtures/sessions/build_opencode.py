"""Build the tiny synthetic OpenCode database used by learn tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SESSION_COLUMNS = "id,project_id,workspace_id,parent_id,fork_session_id,fork_boundary,slug,directory,path,title,version,share_url,summary_additions,summary_deletions,summary_files,summary_diffs,metadata,cost,tokens_input,tokens_output,tokens_reasoning,tokens_cache_read,tokens_cache_write,revert,permission,agent,model,time_created,time_updated,time_idle,time_viewed,idle_outcome,time_compacting,time_archived,time_suspended,resume_attempts"


def build(path: Path, repo: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE session_v2 (id TEXT,project_id TEXT,workspace_id TEXT,parent_id TEXT,fork_session_id TEXT,fork_boundary TEXT,slug TEXT,directory TEXT,path TEXT,title TEXT,version TEXT,share_url TEXT,summary_additions INTEGER,summary_deletions INTEGER,summary_files TEXT,summary_diffs TEXT,metadata TEXT,cost REAL,tokens_input INTEGER,tokens_output INTEGER,tokens_reasoning INTEGER,tokens_cache_read INTEGER,tokens_cache_write INTEGER,revert TEXT,permission TEXT,agent TEXT,model TEXT,time_created INTEGER,time_updated INTEGER,time_idle INTEGER,time_viewed INTEGER,idle_outcome TEXT,time_compacting INTEGER,time_archived INTEGER,time_suspended INTEGER,resume_attempts INTEGER)")
    db.execute("CREATE TABLE session_message (id TEXT,session_id TEXT,type TEXT,seq INTEGER,time_created INTEGER,time_updated INTEGER,data TEXT)")
    values = ["opencode-session", "project", None, None, None, None, "synthetic", str(repo), None, "Synthetic", "2.0.12", None, 0, 0, None, None, None, 0, 0, 0, 0, 0, 0, None, None, None, None, 1788256800000, 1788256800000, None, None, None, None, None, None, 0]
    db.execute(f"INSERT INTO session_v2 ({SESSION_COLUMNS}) VALUES ({','.join('?' for _ in values)})", values)
    for seq, (kind, text) in enumerate((("user", "synthetic request"), ("assistant", "synthetic response")), 1):
        payload = '{"id":"message-%s","sessionID":"opencode-session","type":"%s","time":{"created":1788256800000},"text":"%s"}' % (seq, kind, text)
        db.execute("INSERT INTO session_message VALUES (?,?,?,?,?,?,?)", (f"message-{seq}", "opencode-session", kind, seq, 1788256800000, 1788256800000, payload))
    db.commit()
    db.close()
