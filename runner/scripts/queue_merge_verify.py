"""Verify queue merge, runner restart, CLI smoke, and rollback on a copied tree."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
sys.path[:0] = [
    str(SCRIPT_DIR),
    *(
        str(REPO_ROOT / module / "src")
        for module in ("runner", "data", "workflow", "core", "knowledge")
    ),
]

from live_role_inbox_helpers import assert_clean_restart, tree_digest  # noqa: E402

VOLATILE = frozenset(
    {
        ".cache/data/resources.json",
        ".cache/plans-read-index.sqlite3",
        ".cache/inbox/messages.sqlite3",
        ".cache/inbox/messages.sqlite3-wal",
        ".cache/inbox/messages.sqlite3-shm",
        ".cache/data/queue.sqlite3",
        ".cache/data/queue.sqlite3-wal",
        ".cache/data/queue.sqlite3-shm",
        ".cache/inbox/relay/state.json",
        ".cache/inbox/relay/.state.json.*",
        ".cache/inbox/relay/relay.wake",
        "plans/2026-10-25-native-cutover/notes/soak",
    }
)
QUEUE_DB = Path(".cache/inbox/messages.sqlite3")
LEGACY_DB = Path(".cache/data/queue.sqlite3")
DATABASE_PATHS = (QUEUE_DB, LEGACY_DB)


def queue_rows(database: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Return stable snapshots of all queue-owned tables."""
    tables = (
        "queue_items",
        "queue_events",
        "queue_meta",
        "plan_state",
        "task_state",
        "slots",
        "slot_events",
    )
    with sqlite3.connect(database) as db:
        result = {}
        for table in tables:
            columns = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]
            quoted = ",".join(f'"{column}"' for column in columns)
            result[table] = [
                tuple(row)
                for row in db.execute(
                    f'SELECT {quoted} FROM "{table}" ORDER BY rowid'  # noqa: S608
                )
            ]
    return result


def assert_queue_rows_equal(
    left: dict[str, list[tuple[Any, ...]]], right: dict[str, list[tuple[Any, ...]]]
) -> None:
    """Raise when queue table snapshots differ."""
    if left != right:
        changed = [table for table in left if left.get(table) != right.get(table)]
        raise AssertionError(f"queue row snapshots differ: {', '.join(changed)}")


def verified_copy(source: Path, destination: Path) -> dict[str, str]:
    """Copy a stable working tree and verify source-before/copy/source-after hashes."""

    def discard() -> None:
        if not destination.exists():
            return
        for directory, names, files in os.walk(destination, topdown=False):
            for name in names + files:
                path = Path(directory) / name
                if not path.is_symlink():
                    path.chmod(0o700 if path.is_dir() else 0o600)
            Path(directory).chmod(0o700)
        shutil.rmtree(destination)

    def ignore_live_databases(directory: str, names: list[str]) -> set[str]:
        relative = Path(directory).relative_to(source)
        skipped = set()
        for database in DATABASE_PATHS:
            if relative == database.parent:
                skipped.update(
                    name
                    for name in names
                    if name == database.name
                    or name in {f"{database.name}-wal", f"{database.name}-shm"}
                )
        return skipped

    def backup_databases() -> None:
        for relative in DATABASE_PATHS:
            origin = source / relative
            if not origin.is_file():
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with (
                sqlite3.connect(
                    f"{origin.resolve().as_uri()}?mode=ro", uri=True
                ) as src,
                sqlite3.connect(target) as dst,
            ):
                src.backup(dst)

    for _attempt in range(3):
        before = tree_digest(source, VOLATILE)
        shutil.copytree(
            source, destination, symlinks=True, ignore=ignore_live_databases
        )
        backup_databases()
        copied = tree_digest(destination, VOLATILE)
        after = tree_digest(source, VOLATILE)
        if before == copied == after:
            return {"source_before": before, "copy": copied, "source_after": after}
        discard()
    raise RuntimeError("working tree changed during three copy/checksum attempts")


def load_harness():
    import importlib.util

    path = SCRIPT_DIR / "live_role_inbox_verify.py"
    spec = importlib.util.spec_from_file_location("live_role_inbox_verify", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load scratch runner harness")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call(
    harness: Any, working: Path, env: dict[str, str], *args: str
) -> dict[str, Any]:
    result = harness.command(list(args), working=working, env=env)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"expected JSON from varde {' '.join(args)}: {result.stdout}"
        ) from error


def start_stop(harness: Any, env: dict[str, str], log: Path) -> int:
    port = harness.free_port()
    process = harness.start_runner(env, log, port)
    harness.stop_runner(process)
    assert_clean_restart(log.read_text(encoding="utf-8"))
    return port


def verify_role_mail(
    harness: Any, working: Path, env: dict[str, str]
) -> dict[str, str]:
    """Send, read, and acknowledge a role message in the shared database."""
    holder = harness.add_holder(working, "t05-combined-mail-proof", "initial")
    mail_id = harness.send_role_mail(
        working, env, "t05 combined mail and queue transaction proof"
    )
    if mail_id not in harness.role_unread(working, [holder])[holder]:
        raise RuntimeError("role mail was not visible to its bound holder")
    call(harness, working, env, "msg", "read", "--as", holder, "--json")
    harness.command(["msg", "ack", mail_id, "--as", holder], working=working, env=env)
    with sqlite3.connect(working / QUEUE_DB) as db:
        acked = db.execute(
            "SELECT 1 FROM deliveries WHERE message_id=? AND reader=? "
            "AND event='acked'",
            (mail_id, holder),
        ).fetchone()
    if acked is None:
        raise RuntimeError("role mail acknowledgement was not recorded")
    return {"message_id": mail_id, "holder": holder}


def run(source: Path, scratch_parent: Path | None = None) -> dict[str, Any]:
    harness = load_harness()
    scratch_root = Path(
        tempfile.mkdtemp(prefix="varde-queue-merge-", dir=scratch_parent)
    )
    working = scratch_root / "working"
    hashes = verified_copy(source.resolve(), working)
    env = harness.runner_environment(
        working, scratch_root / "config", scratch_root / "state", scratch_root / "home"
    )
    from varde_runner.config import default_toml

    config_dir = Path(env["VARDE_RUNNER_CONFIG_DIR"])
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "runner.toml").write_text(default_toml(), encoding="utf-8")
    from varde_data.backends.sqlite.queue_schema import QUEUE_MARKER_VERSION
    from varde_data.queue_store import status
    from varde_data.store_mode import read_store_mode

    marker = int(
        (working / ".cache/data/queue.version").read_text(encoding="ascii").strip()
    )
    if marker != QUEUE_MARKER_VERSION - 1:
        raise RuntimeError(f"expected legacy queue marker 3, found {marker}")
    mode = status(working)
    if mode.get("mode") != "sqlite":
        raise RuntimeError(f"queue is not SQLite-backed: {mode}")
    mail_mode = read_store_mode(working)
    if (
        mail_mode is None
        or mail_mode.primary != "sqlite"
        or mail_mode.mirror != "none"
        or mail_mode.generation != 4
    ):
        raise RuntimeError(f"expected mail SQLite generation 4, found {mail_mode}")
    premerge = queue_rows(working / LEGACY_DB)
    merge = call(harness, working, env, "plan", "queue", "merge-role-inbox", "--json")
    merged = queue_rows(working / QUEUE_DB)
    assert_queue_rows_equal(premerge, merged)

    log = scratch_root / "runner.log"
    first_port = start_stop(harness, env, log)
    call(harness, working, env, "plan", "queue", "status", "--json")
    from varde_data.queue import open_slots

    mail_proof = verify_role_mail(harness, working, env)

    slot_id = "t05-scratch-builder"
    slot = open_slots(working).register(
        slot_id,
        plan_id="t05-scratch",
        role="builder",
        agent_ref="t05-scratch-agent",
        session_id="t05-scratch-session",
    )
    (working / ".cache/data/resources.json").write_text(
        json.dumps(
            {
                "taken_at": datetime.now(UTC).isoformat(),
                "providers": {},
                "rss_mb": 1,
                "cpu_pct": 1,
                "processes": 1,
                "live_workers": 0,
            }
        ),
        encoding="utf-8",
    )
    item_id = "t05-scratch-queue-proof"
    call(
        harness,
        working,
        env,
        "plan",
        "queue",
        "enqueue",
        "--plan-dir",
        str(working),
        "--id",
        item_id,
        "--role",
        "builder",
    )
    pulled = call(
        harness,
        working,
        env,
        "plan",
        "queue",
        "pull",
        "--role",
        "builder",
        "--slot",
        slot_id,
        "--epoch",
        str(slot.epoch),
        "--json",
    )
    pull_data = pulled.get("data", pulled)
    if pull_data.get("item", {}).get("id") != item_id:
        raise RuntimeError(f"scratch queue item was not claimed: {pulled}")
    call(
        harness,
        working,
        env,
        "plan",
        "queue",
        "finish",
        "--item",
        item_id,
        "--slot",
        slot_id,
        "--epoch",
        str(slot.epoch),
        "--json",
    )
    second_port = start_stop(harness, env, log)

    rollback = call(
        harness, working, env, "plan", "queue", "rollback-role-inbox", "--json"
    )
    after_rollback = queue_rows(working / LEGACY_DB)
    for table, rows in premerge.items():
        if table in {"queue_items", "queue_events", "slots", "slot_events"}:
            if any(row not in after_rollback[table] for row in rows):
                raise AssertionError(f"rollback lost original {table} rows")
        elif after_rollback[table] != rows:
            raise AssertionError(f"rollback changed original {table} rows")
    if (
        int((working / ".cache/data/queue.version").read_text(encoding="ascii").strip())
        != 3
    ):
        raise RuntimeError("rollback did not restore queue marker 3")
    third_port = start_stop(harness, env, log)
    return {
        "copy_hashes": hashes,
        "scratch": str(scratch_root),
        "queue_before_rows": {key: len(value) for key, value in premerge.items()},
        "merge": merge,
        "rollback": rollback,
        "ports": [first_port, second_port, third_port],
        "cli_smoke": ["status", "pull", "finish"],
        "mail_smoke": mail_proof | {"acked": True},
        "mail_generation": mail_mode.generation,
        "runner_restarts": 3,
        "rollback_marker": 3,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.home() / "source/agent-memory/projects/varde-py/working",
    )
    parser.add_argument("--scratch-parent", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.scratch_parent), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
