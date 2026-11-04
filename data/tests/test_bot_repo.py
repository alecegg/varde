from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from varde_data.bot import open_bot
from varde_data.config import DataConfig
from varde_data.open import open_data


def append(repo, **overrides):
    fields = {
        "phase": "call",
        "action": "launch",
        "route": "POST /api/agents",
        "args_digest": "d",
        "redacted_args": "{}",
        "actor": "bot:manager",
        "status": "allowed",
    }
    return repo.append_audit(**{**fields, **overrides})


def test_the_repository_has_no_update_or_delete_method(tmp_path: Path) -> None:
    repo = open_bot(tmp_path)
    public = {name for name in dir(repo) if not name.startswith("_")}
    assert not {
        name for name in public if name.startswith(("update", "delete", "remove"))
    }


def test_rows_are_appended_in_order_and_paged_newest_first(tmp_path: Path) -> None:
    repo = open_bot(tmp_path)
    ids = [append(repo, action=f"a{n}").id for n in range(5)]
    assert ids == sorted(ids)
    page = repo.audit_page(limit=2)
    assert [row.action for row in page] == ["a4", "a3"]
    older = repo.audit_page(before=page[-1].id, limit=10)
    assert [row.action for row in older] == ["a2", "a1", "a0"]
    first = repo.audit_page(limit=1)[0]
    assert (
        first.phase == "call"
        and first.actor == "bot:manager"
        and first.ts.endswith("Z")
    )


def test_database_refuses_update_and_delete_even_by_raw_sql(tmp_path: Path) -> None:
    repo = open_bot(tmp_path)
    row = append(repo)
    repo.mark_evented(row.id, "m1")
    raw = sqlite3.connect(tmp_path / ".cache" / "dashboard" / "chat.sqlite3")
    for statement in (
        "UPDATE bot_audit SET status = 'x'",
        "DELETE FROM bot_audit",
        "UPDATE bot_audit_events SET message_id = 'x'",
        "DELETE FROM bot_audit_events",
    ):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            raw.execute(statement)
    raw.close()
    assert repo.audit_page()[0].status == "allowed"


def test_invalid_phase_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="phase"):
        append(open_bot(tmp_path), phase="update")


def test_unevented_rows_are_call_rows_that_are_not_reads(tmp_path: Path) -> None:
    repo = open_bot(tmp_path)
    denied = append(repo, status="denied")
    done = append(repo)
    append(repo, phase="result", status="ok")
    append(repo, status="read")
    assert [row.id for row in repo.unevented_audit()] == [denied.id, done.id]
    assert repo.mark_evented(denied.id, "m1")
    assert not repo.mark_evented(denied.id, "m2")
    assert [row.id for row in repo.unevented_audit()] == [done.id]


def test_audit_since_actor_filter_includes_descendants_but_not_lookalikes(
    tmp_path: Path,
) -> None:
    repo = open_bot(tmp_path)
    append(repo)
    append(repo, actor="bot:manager/child")
    append(repo, actor="bot:manager-evil")
    assert len(repo.audit_since("0000", actor="bot:manager")) == 2
    assert len(repo.audit_since("0000", actor="bot:manager/child")) == 1
    assert len(repo.audit_since("0000")) == 3


def test_state_persists_across_reopen(tmp_path: Path) -> None:
    repo = open_bot(tmp_path)
    assert repo.get_state("run") is None
    repo.set_state("run", "paused", "loop", "system:governor")
    again = open_bot(tmp_path).get_state("run")
    assert again is not None
    assert (again.state, again.reason, again.changed_by) == (
        "paused",
        "loop",
        "system:governor",
    )
    repo.set_state("run", "running", None, "user")
    assert open_bot(tmp_path).get_state("run").state == "running"  # type: ignore[union-attr]
    assert len(open_bot(tmp_path).audit_page()) == 0


def test_domain_is_available_through_open_data(tmp_path: Path) -> None:
    data = open_data(tmp_path, DataConfig())
    row = append(data.bot)
    assert data.bot.audit_page()[0].id == row.id


def test_bot_tables_live_in_the_chat_database_beside_the_chat_schema(
    tmp_path: Path,
) -> None:
    from varde_data.backends.sqlite.chat import SCHEMA_VERSION
    from varde_data.chat import open_chat

    for first_bot in (True, False):
        root = tmp_path / str(first_bot)
        if first_bot:
            bot, chat = open_bot(root), open_chat(root)
        else:
            chat, bot = open_chat(root), open_bot(root)
        append(bot)
        chat.append_event("bot", "Bot: launch", None)
        raw = sqlite3.connect(root / ".cache" / "dashboard" / "chat.sqlite3")
        tables = {r[0] for r in raw.execute("SELECT name FROM sqlite_master")}
        assert {"bot_audit", "bot_state", "chat_threads"} <= tables
        assert raw.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        raw.close()
        assert not (root / ".cache" / "dashboard" / "bot.sqlite3").exists()


def test_the_bot_domain_follows_the_chat_backend_setting(tmp_path: Path) -> None:
    data = open_data(tmp_path, DataConfig(backends={"chat": "sqlite"}))
    assert data.bot.audit_page() == []
