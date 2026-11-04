# ruff: noqa: S603, S607
from __future__ import annotations

import io
import json
import subprocess

import pytest
from varde_core.memory_dirs import project_key
from varde_learn.loop import cli_memory_migrate
from varde_learn.memory import migrate, store


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


def row(
    pid,
    note="a note",
    decision="approved",
    target: str | None = "user",
    ts="2026-01-01T00:00:00+00:00",
    **extra,
):
    return {
        "note": note,
        "source_tier": extra.pop("source_tier", "user"),
        "target_tier": target,
        "outcome": "decide",
        "reason": "r",
        "proposal_id": pid,
        "decision": decision,
        "timestamp": ts,
        **extra,
    }


def write_log(path, rows, torn=""):
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n" + torn, encoding="utf-8"
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    store_dir = tmp_path / "learn"
    store_dir.mkdir()
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store_dir))
    monkeypatch.setenv("VARDE_MEMORY_DIR", str(tmp_path / "mem"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    monkeypatch.chdir(work)
    return store_dir / migrate.OLD_LOG, tmp_path / "mem", work


def run(*argv):
    out = Io()
    code = cli_memory_migrate.run(["migrate", *argv, "--json"], out)
    assert code == 0, out.stderr.getvalue()
    return json.loads(out.stdout.getvalue())["data"]


def entries(root):
    return {e.id: e for e in store.load_entries(root)}


def test_tier_mapping_and_counts(env) -> None:
    log, root, work = env
    write_log(
        log,
        [
            row("u1", target="user"),
            row("p1", target="project"),
            row("r1", target="role", source_tier="role"),
            row("pend", decision="pending"),
            row("flag", decision="flagged", target=None),
            row("rolled", target="user", source_tier="role"),
        ],
        torn='{"proposal_id": "torn',
    )
    data = run()
    assert data["counts"]["migrated"] == 3
    assert data["counts"]["skipped"] == 2
    assert data["counts"]["archived_role"] == 1
    found = entries(root)
    assert set(found) == {"u1", "p1", "rolled"}
    assert found["u1"].scope == "global"
    assert found["rolled"].scope == "global"
    assert found["p1"].scope == "project"
    assert found["p1"].scope_key == project_key(work)
    assert found["u1"].source == "memory-tier u1"
    assert (log.parent / migrate.MIGRATED_LOG).exists()
    assert not log.exists()


def test_later_rows_keep_id_and_created_and_rerun_is_idempotent(env) -> None:
    log, root, _ = env
    write_log(
        log,
        [
            row("same", decision="pending", ts="2026-01-01T00:00:00+00:00"),
            row("same", decision="approved", ts="2026-02-02T00:00:00+00:00"),
        ],
    )
    run()
    entry = entries(root)["same"]
    assert entry.created == "2026-01-01T00:00:00+00:00"
    (log.parent / migrate.MIGRATED_LOG).rename(log)
    data = run()
    assert data["counts"]["migrated"] == 0
    assert data["counts"]["existing"] == 1
    assert len(entries(root)) == 1


def test_applied_row_with_existing_target_is_already_applied(env, tmp_path) -> None:
    log, root, _ = env
    inside = tmp_path / "mem" / "moved.md"
    inside.parent.mkdir(parents=True)
    inside.write_text("x")
    write_log(
        log,
        [
            row("done", decision="applied", target_path=str(inside)),
            row(
                "gone", decision="applied", target_path=str(tmp_path / "mem" / "no.md")
            ),
        ],
    )
    data = run()
    assert data["counts"]["already_applied"] == 1
    assert set(entries(root)) == {"gone"}


def test_secret_note_is_reported_not_fatal(env) -> None:
    log, root, _ = env
    write_log(
        log,
        [row("bad", note="password = hunter2hunter2"), row("good")],
    )
    data = run()
    assert data["counts"]["failed"] == 1
    assert "bad" in data["failed"][0]
    assert set(entries(root)) == {"good"}
    assert "bad" in data["text"]
    assert not log.exists()  # failed rows are skipped and listed, not an abort
    assert (log.parent / migrate.MIGRATED_LOG).exists()  # renamed, never deleted


def test_project_row_in_other_repo_uses_that_repo_key(env, tmp_path) -> None:
    log, root, work = env
    other = tmp_path / "Other Repo"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    note = other / "note.md"
    note.write_text("n")
    write_log(log, [row("o1", target="project", source_path=str(note))])
    run()
    assert entries(root)["o1"].scope_key == project_key(other)
    assert entries(root)["o1"].scope_key != project_key(work)


def test_project_root_option_for_notes_outside_a_repo(env, tmp_path) -> None:
    log, root, _ = env
    loose = tmp_path / "loose"
    loose.mkdir()
    target = tmp_path / "proj"
    target.mkdir()
    subprocess.run(["git", "init", "-q", str(target)], check=True)
    write_log(log, [row("l1", target="project", source_path=str(loose / "n.md"))])
    run("--project-root", str(target))
    assert entries(root)["l1"].scope_key == project_key(target)


def test_dry_run_writes_nothing(env) -> None:
    log, root, _ = env
    write_log(log, [row("d1")])
    data = run("--dry-run")
    assert data["counts"]["migrated"] == 1
    assert not root.exists()
    assert log.exists()
    assert not (log.parent / migrate.MIGRATED_LOG).exists()


def test_missing_log_reports_zero(env) -> None:
    data = run()
    assert sum(data["counts"].values()) == 0


def test_unresolved_project_row_keeps_the_log(env, tmp_path) -> None:
    log, root, _ = env
    loose = tmp_path / "loose"
    loose.mkdir()
    cwd_free = tmp_path / "nowhere"
    cwd_free.mkdir()
    write_log(log, [row("l1", target="project", source_path=str(loose / "n.md"))])
    report = migrate.migrate(
        migrate.read_rows(log),
        root,
        project_of=lambda _row: None,
        applied_in_place=lambda _row: False,
        dry_run=False,
    )
    assert report.unresolved == ["l1"] and not report.complete()


def test_project_key_from_linked_worktree_matches_main(env, tmp_path) -> None:
    log, root, work = env
    subprocess.run(
        ["git", "-C", str(work), "-c", "user.name=t", "-c", "user.email=t@x",
         "commit", "-q", "--allow-empty", "-m", "i"],
        check=True,
    )  # fmt: skip
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "-C", str(work), "worktree", "add", "-q", str(linked)], check=True
    )
    note = linked / "note.md"
    note.write_text("n")
    write_log(log, [row("w1", target="project", source_path=str(note))])
    run()
    assert entries(root)["w1"].scope_key == project_key(work)
