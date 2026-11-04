"""Exercise real inbox import, SQLite mode, restart, retirement, and rollback on a copy.

The source tree is read-only. All mutation and runner processes use the copy.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from live_role_inbox_helpers import tree_digest

REPO_ROOT = Path(__file__).resolve().parents[2]
VOLATILE = frozenset(
    {
        ".cache/data/resources.json",
        ".cache/plans-read-index.sqlite3",
        ".cache/inbox/relay/state.json",
        ".cache/inbox/relay/.state.json.*",
        "plans/2026-10-25-native-cutover/notes/soak",
    }
)


def load_previous_harness():
    spec = importlib.util.spec_from_file_location(
        "live_role_inbox_verify", Path(__file__).with_name("live_role_inbox_verify.py")
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load scratch runner harness")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def consistent_copy(source: Path, destination: Path) -> dict[str, str]:
    def discard_copy() -> None:
        if not destination.exists():
            return
        for directory, names, files in os.walk(destination, topdown=False):
            for name in names + files:
                path = Path(directory) / name
                if not path.is_symlink():
                    path.chmod(0o700 if path.is_dir() else 0o600)
            Path(directory).chmod(0o700)
        shutil.rmtree(destination, ignore_errors=True)

    def ignore_atomic_relay_state(directory: str, names: list[str]) -> set[str]:
        if Path(directory) == source / ".cache" / "inbox" / "relay":
            return {name for name in names if name.startswith(".state.json.")}
        return set()

    for _attempt in range(3):
        before = tree_digest(source, VOLATILE)
        try:
            shutil.copytree(
                source,
                destination,
                symlinks=True,
                ignore=ignore_atomic_relay_state,
            )
        except shutil.Error, OSError:
            discard_copy()
            continue
        copied = tree_digest(destination, VOLATILE)
        after = tree_digest(source, VOLATILE)
        if before == copied == after:
            return {"source_before": before, "copy": copied, "source_after": after}
        discard_copy()
    raise RuntimeError("source changed during three copy/checksum attempts")


def file_unread_snapshot(working: Path) -> dict[str, list[str]]:
    from varde_data.config import load_data_config
    from varde_data.messages_transfer import _reader_names
    from varde_data.open import open_data

    messages = open_data(working, load_data_config()).messages
    return {
        reader: sorted(item.id for item in messages.peek_unread(reader) if item.id)
        for reader in _reader_names(messages, working)
    }


def flip_to_sqlite(working: Path) -> None:
    from varde_data.store_mode import set_store_mode

    set_store_mode(working, "mirror-files")
    set_store_mode(working, "mirror-sqlite")
    set_store_mode(working, "sqlite")


def flip_to_files(working: Path) -> None:
    from varde_data.store_mode import read_store_mode, set_store_mode

    current = read_store_mode(working)
    if current is None:
        raise RuntimeError("message store mode marker is missing")
    if current.primary == "sqlite" and current.mirror == "none":
        set_store_mode(working, "mirror-sqlite")
    elif current.primary != "sqlite" or current.mirror != "files":
        raise RuntimeError(
            f"cannot roll back from mode {current.primary}/{current.mirror}"
        )
    set_store_mode(working, "mirror-files")
    set_store_mode(working, "files")


def clean_doctor(working: Path, env: dict[str, str]) -> dict[str, Any]:
    harness = load_previous_harness()
    result = harness.command(["msg", "doctor", "--json"], working=working, env=env)
    return json.loads(result.stdout)


def runner_env(harness: Any, scratch_root: Path, working: Path) -> dict[str, str]:
    env = harness.runner_environment(
        working,
        scratch_root / "config",
        scratch_root / "state",
        scratch_root / "home",
    )
    from varde_runner.config import default_toml

    config = Path(env["VARDE_RUNNER_CONFIG_DIR"])
    config.mkdir(parents=True, exist_ok=True)
    (config / "runner.toml").write_text(default_toml(), encoding="utf-8")
    return env


def import_and_verify(
    harness: Any, working: Path, env: dict[str, str]
) -> tuple[str, str]:
    imported = harness.command(
        ["msg", "store", "import", "--from", "files", "--to", "sqlite"],
        working=working,
        env=env,
    )
    flip_to_sqlite(working)
    verified = harness.command(
        ["msg", "store", "verify", "--from", "files", "--to", "sqlite"],
        working=working,
        env=env,
    )
    return imported.stdout.strip(), verified.stdout.strip()


def start_and_restart(harness: Any, env: dict[str, str], log: Path) -> None:
    from live_role_inbox_helpers import assert_clean_restart

    for _ in range(2):
        process = harness.start_runner(env, log, harness.free_port())
        harness.stop_runner(process)
    assert_clean_restart(log.read_text(encoding="utf-8"))


def bind_role_holder(working: Path) -> str:
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.records.addresses import ReaderContext
    from varde_data.service import AddressService

    plan_id = "t06-role-flip-proof"
    holder = f"{plan_id}-builder"
    data = open_data(working, load_data_config())
    AddressService(data.addresses, data.messages).add_alias(holder, plan_id)
    marker = data.addresses.issue(
        holder,
        ttl=timedelta(seconds=3600),
        uses=1,
        supersede=True,
        now=datetime.now(UTC),
        issuer="t06",
    )
    redeemed = data.addresses.redeem(
        marker,
        "t06-session",
        "codex",
        ReaderContext(cwd=str(working), paseo_id="t06-session"),
        now=datetime.now(UTC),
    )
    if not redeemed:
        raise RuntimeError("could not bind proof holder")
    return holder


def send_and_read_role_mail(
    harness: Any, working: Path, env: dict[str, str], holder: str
) -> str:
    sent = harness.command(
        [
            "msg",
            "send",
            "--from",
            "main",
            "--to",
            "builder",
            "--kind",
            "info",
            "t06 role mail",
        ],
        working=working,
        env=env,
    )
    message_id = sent.stdout.split()[1]
    read = harness.command(
        ["msg", "read", "--as", holder, "--json"], working=working, env=env
    )
    rows = json.loads(read.stdout).get("data", {}).get("messages", [])
    if not any(row.get("id") == message_id for row in rows):
        raise RuntimeError("bound role holder did not read role mail")
    return message_id


def retire_and_check_doctor(
    working: Path, scratch_root: Path, env: dict[str, str]
) -> tuple[str, dict[str, Any]]:
    from varde_workflow.inbox import append_message, read_all

    old_mail = append_message(
        "main",
        "python-port-retirement-proof",
        "info",
        "scratch-only retirement fixture",
        working=working,
        now=datetime.now(UTC) - timedelta(days=45),
    )
    append_message(
        "scratch-test",
        "main",
        "info",
        "scratch-only manager visibility fixture",
        working=working,
    )
    audit_dir = scratch_root / "audit"
    retired = load_previous_harness().command(
        ["msg", "retire", "--dry-run", str(audit_dir)], working=working, env=env
    )
    dry_run = audit_dir / "retire-dry-run.json"
    approved = load_previous_harness().command(
        ["msg", "retire", "--apply", str(dry_run)], working=working, env=env
    )
    audit = audit_dir / "retire-audit.json"
    archive = json.loads(audit.read_text(encoding="utf-8"))
    if old_mail.id not in {row["id"] for row in archive["messages"]}:
        raise RuntimeError("the old scratch fixture was not archived")
    doctor = clean_doctor(working, env)
    assert_doctor_only_lists_live(working, doctor)
    load_previous_harness().command(
        ["msg", "retire", "--restore", str(audit)], working=working, env=env
    )
    if not any(item.id == old_mail.id for item in read_all(working)):
        raise RuntimeError("restore did not retain the archived message record")
    return retired.stdout.strip() + "\n" + approved.stdout.strip(), doctor


def assert_doctor_only_lists_live(working: Path, doctor: dict[str, Any]) -> None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    data = open_data(working, load_data_config())
    live = set(data.addresses.live_addresses(datetime.now(UTC)))
    retired = set(data.addresses.retired_records())
    listed = {row["address"] for row in doctor["recipients"]}
    if listed & retired:
        raise RuntimeError(
            "doctor still lists backlog for an explicitly retired address"
        )
    if "main" not in listed:
        raise RuntimeError("doctor hid the manager inbox")
    if not live:
        raise RuntimeError("scratch runner has no live address to verify")


def rollback_and_verify(
    harness: Any, working: Path, env: dict[str, str], log: Path
) -> tuple[int, str]:
    from live_role_inbox_helpers import assert_clean_restart

    before = file_unread_snapshot(working)
    flip_to_files(working)
    after = file_unread_snapshot(working)
    if before != after:
        differences = {
            reader: {
                "sqlite_only": sorted(
                    set(before.get(reader, [])) - set(after.get(reader, []))
                ),
                "files_only": sorted(
                    set(after.get(reader, [])) - set(before.get(reader, []))
                ),
            }
            for reader in sorted(before.keys() | after.keys())
            if before.get(reader, []) != after.get(reader, [])
        }
        raise RuntimeError(f"rollback changed per-reader unread sets: {differences}")
    verified = harness.command(
        ["msg", "store", "verify", "--from", "files", "--to", "sqlite"],
        working=working,
        env=env,
    )
    process = harness.start_runner(env, log, harness.free_port())
    harness.stop_runner(process)
    assert_clean_restart(log.read_text(encoding="utf-8"))
    return len(after), verified.stdout.strip()


def run(source: Path, keep: bool = False) -> dict[str, Any]:
    harness = load_previous_harness()
    scratch_root = Path(tempfile.mkdtemp(prefix="varde-mail-flip-"))
    working = scratch_root / "working"
    try:
        copy_hashes = consistent_copy(source.resolve(), working)
        backup = scratch_root / "inbox-backup"
        harness.backup_copied_inbox(working, backup)
        env = runner_env(harness, scratch_root, working)
        imported, verified = import_and_verify(harness, working, env)
        log = scratch_root / "runner.log"
        start_and_restart(harness, env, log)
        holder = bind_role_holder(working)
        message_id = send_and_read_role_mail(harness, working, env, holder)
        retirement, doctor = retire_and_check_doctor(working, scratch_root, env)
        reader_count, rollback_verify = rollback_and_verify(harness, working, env, log)
        return {
            "scratch": str(scratch_root),
            "kept": keep,
            "copy_checksum_pass": copy_hashes,
            "excluded_volatile_paths": sorted(VOLATILE),
            "backup": str(backup),
            "import": imported,
            "sqlite_verify": verified,
            "runner_started_and_restarted": True,
            "runner_log": str(log),
            "runner_started_after_rollback": True,
            "role_message_id": message_id,
            "role_read": True,
            "retirement": retirement,
            "doctor_recipients": [row["address"] for row in doctor["recipients"]],
            "unread_sets_identical_after_rollback": True,
            "rollback_reader_count": reader_count,
            "rollback_verify": rollback_verify,
        }
    finally:
        if not keep:
            shutil.rmtree(scratch_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.source, args.keep),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
