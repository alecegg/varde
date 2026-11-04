"""Prove role inbox behavior against a temporary copy of live working data.

Example:
    uv run python runner/scripts/live_role_inbox_verify.py \
      --source /Users/alec/source/agent-memory/projects/varde-py/working

The script never opens the source for writing. It copies the complete working
tree to a temporary directory, backs up the copied inbox, and performs every
store transition and runner launch on that copy.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.request import ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workflow" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core" / "src"))

from live_role_inbox_helpers import (
    assert_clean_restart,
    one_claim,
    same_unread_set,
    tree_digest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_START_TIMEOUT_S = 45
VOLATILE_SOURCE_PATHS = frozenset(
    {
        ".cache/data/resources.json",
        ".cache/plans-read-index.sqlite3",
        ".cache/inbox/relay/state.json",
        "plans/2026-10-25-native-cutover/notes/soak",
    }
)


class DrillFailure(RuntimeError):
    """An acceptance check failed in the isolated drill."""


def runner_environment(
    working: Path, config: Path, state: Path, home: Path
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(config),
            "XDG_STATE_HOME": str(state),
            "VARDE_CONFIG_DIR": str(config / "varde"),
            "VARDE_RUNNER_CONFIG_DIR": str(config / "runner"),
            "VARDE_RUNNER_STATE_DIR": str(state / "runner"),
            "VARDE_WORKING_DIR": str(working),
            "VARDE_DATA_ADDRESSES_BACKEND": "files",
            "VARDE_DATA_MESSAGES_BACKEND": "files",
            "VARDE_RUNNER_RELAY": "off",
        }
    )
    env["PATH"] = (
        str(Path(sys.executable).absolute().parent) + os.pathsep + env.get("PATH", "")
    )
    return env


def backup_copied_inbox(working: Path, backup: Path) -> None:
    """Copy inbox files and use SQLite's backup API for its live database."""
    from varde_data.messages import message_store_files, messages_db_path

    inbox = working / ".cache" / "inbox"
    backup.mkdir(parents=True)
    database_files = set(message_store_files(working))
    shutil.copytree(
        inbox,
        backup / "inbox",
        dirs_exist_ok=True,
        ignore=lambda _directory, names: {
            name
            for name in names
            if (inbox / name) in database_files or name.endswith(("-wal", "-shm"))
        },
    )
    database = messages_db_path(working)
    if database.is_file():
        target = backup / "messages.sqlite3"
        with (
            closing(
                sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
            ) as source,
            closing(sqlite3.connect(target)) as destination,
        ):
            source.backup(destination)


def reset_copied_inbox(working: Path) -> None:
    """Start the drill with an empty copied inbox after the backup is safe."""
    inbox = working / ".cache" / "inbox"
    if inbox.exists():
        for root, directories, files in os.walk(inbox, topdown=False):
            for name in files:
                path = Path(root) / name
                if not path.is_symlink():
                    path.chmod(0o600)
            for name in directories:
                path = Path(root) / name
                if not path.is_symlink():
                    path.chmod(0o700)
            Path(root).chmod(0o700)
        shutil.rmtree(inbox)
    inbox.mkdir(parents=True)


def command(
    args: list[str], *, working: Path, env: dict[str, str], check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell, isolated workdir.
        [
            sys.executable,
            "-c",
            "from varde.cli import main; raise SystemExit(main())",
            *args,
        ],
        cwd=working,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=600,
    )
    if check and result.returncode:
        raise DrillFailure(
            f"command failed ({result.returncode}): varde {' '.join(args)}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def ensure_message_sqlite(working: Path, env: dict[str, str]) -> str:
    result = command(
        ["msg", "store", "import", "--from", "files", "--to", "sqlite"],
        working=working,
        env=env,
    )
    return result.stdout.strip()


def activate_sqlite_mail(working: Path) -> None:
    """Move the verified import through both mirror states into SQLite mode."""
    from varde_data.backends.mirror.messages import MirrorMessages
    from varde_data.store_mode import set_store_mode

    set_store_mode(working, "mirror-files")
    if not MirrorMessages(working, "files", "sqlite").sync():
        raise DrillFailure("files-to-SQLite mirror sync failed")
    set_store_mode(working, "mirror-sqlite")
    set_store_mode(working, "sqlite")


def require_sqlite_queue(working: Path) -> None:
    from varde_data.queue_store import status

    state = status(working)
    if state.get("mode") != "sqlite":
        raise DrillFailure(
            "copied plan queue is not in SQLite mode; the live claim drill requires "
            "an already-migrated queue store"
        )


def add_holder(working: Path, plan_id: str, session: str) -> str:
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.records.addresses import ReaderContext
    from varde_data.service import AddressService

    holder = f"{plan_id}-builder"
    data = open_data(working, load_data_config())
    AddressService(data.addresses, data.messages).add_alias(holder, plan_id)
    now = datetime.now(UTC)
    marker = data.addresses.issue(
        holder,
        ttl=timedelta(hours=2),
        uses=1,
        supersede=True,
        now=now,
        issuer="live-verify",
    )
    context = ReaderContext(cwd=str(working), paseo_id=f"verify-{session}")
    if not data.addresses.redeem(marker, session, "codex", context, now=now):
        raise DrillFailure(f"could not bind scratch holder {holder}")
    return holder


def unbind_holder(working: Path, holder: str) -> None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    addresses = open_data(working, load_data_config()).addresses
    if not addresses.unbind(holder, datetime.now(UTC)):
        raise DrillFailure(f"could not unbind predecessor {holder}")


def send_role_mail(working: Path, env: dict[str, str], text: str) -> str:
    result = command(
        ["msg", "send", "--from", "main", "--to", "builder", "--kind", "info", text],
        working=working,
        env=env,
    )
    message_id = result.stdout.split()[1]
    if not message_id:
        raise DrillFailure(f"send returned no message id: {result.stdout}")
    return message_id


def role_unread(working: Path, holders: list[str]) -> dict[str, list[str]]:
    from varde_data.role_inbox import select_role_inbox

    inbox = select_role_inbox(working)
    if inbox is None:
        raise DrillFailure("role inbox did not select SQLite mode")
    return {
        holder: [
            message.id
            for message in inbox.unread("builder", holder)
            if message.id is not None
        ]
        for holder in holders
    }


def verify_delivery_and_cursors(
    working: Path,
    env: dict[str, str],
    holders: list[str],
    run_id: str,
) -> dict[str, Any]:
    from varde_workflow.inbox import delivery_events

    message_id = send_role_mail(working, env, f"shared-{run_id}")
    before = role_unread(working, holders)
    if any(message_id not in ids for ids in before.values()):
        raise DrillFailure(f"role send did not reach all holders: {before}")
    first_read = command(
        ["msg", "read", "--as", holders[0], "--json"], working=working, env=env
    )
    read_payload = json.loads(first_read.stdout)
    data = read_payload.get("data", {}) if isinstance(read_payload, dict) else {}
    read_rows = data.get("messages", []) if isinstance(data, dict) else []
    if not any(
        row.get("id") == message_id for row in read_rows if isinstance(row, dict)
    ):
        raise DrillFailure("msg read did not return the shared role message")
    after = role_unread(working, holders)
    if message_id in after[holders[0]] or message_id not in after[holders[1]]:
        raise DrillFailure(f"holders did not retain independent cursors: {after}")
    events = [
        event for event in delivery_events(working) if event["message_id"] == message_id
    ]
    expected = {"delivered", "acked"}
    holder_events = {
        event["event"]
        for event in events
        if event.get("reader") == holders[0] and event.get("event") in expected
    }
    if holder_events != expected:
        raise DrillFailure(f"read did not record delivery and ack: {events}")
    return {
        "message_id": message_id,
        "read_holder": holders[0],
        "unread_after_read": after,
        "events": sorted(holder_events),
    }


def verify_successor(working: Path, env: dict[str, str], run_id: str) -> dict[str, Any]:
    predecessor_session = f"successor-old-{run_id}"
    successor_session = f"successor-new-{run_id}"
    predecessor = add_holder(working, f"lv{run_id}pred", predecessor_session)
    acknowledged_id = send_role_mail(working, env, f"successor-read-{run_id}")
    read = command(
        ["msg", "read", "--as", predecessor, "--json"], working=working, env=env
    )
    payload = json.loads(read.stdout)
    rows = payload.get("data", {}).get("messages", [])
    read_ids = {row.get("id") for row in rows if isinstance(row, dict)}
    if acknowledged_id not in read_ids:
        raise DrillFailure("predecessor did not read its role message")
    unread_id = send_role_mail(working, env, f"successor-unread-{run_id}")
    unbind_holder(working, predecessor)
    successor = add_holder(working, f"lv{run_id}next", successor_session)
    successor_read = command(
        ["msg", "read", "--as", successor, "--json"], working=working, env=env
    )
    successor_payload = json.loads(successor_read.stdout)
    successor_rows = successor_payload.get("data", {}).get("messages", [])
    inherited_ids = {row.get("id") for row in successor_rows if isinstance(row, dict)}
    if unread_id not in inherited_ids or acknowledged_id in inherited_ids:
        raise DrillFailure(
            "new successor did not inherit only predecessor unread mail: "
            f"{sorted(str(message_id) for message_id in inherited_ids)}"
        )
    return {
        "predecessor": predecessor,
        "successor": successor,
        "predecessor_session": predecessor_session,
        "successor_session": successor_session,
        "acknowledged_id": acknowledged_id,
        "inherited_unread_id": unread_id,
        "distinct_holder_and_session": True,
    }


def verify_first_holder_mail(
    working: Path, env: dict[str, str], run_id: str
) -> dict[str, Any]:
    plan_id = f"lv{run_id}first"
    holder = f"{plan_id}-builder"
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.service import AddressService

    data = open_data(working, load_data_config())
    AddressService(data.addresses, data.messages).add_alias(holder, plan_id)
    result = command(
        [
            "msg",
            "send",
            "--from",
            "main",
            "--to",
            f"builder:{plan_id}",
            "--kind",
            "info",
            f"queued-{run_id}",
        ],
        working=working,
        env=env,
    )
    message_id = result.stdout.split()[1]
    holder = add_holder(working, plan_id, f"first-holder-{run_id}")
    read = command(["msg", "read", "--as", holder, "--json"], working=working, env=env)
    payload = json.loads(read.stdout)
    rows = payload.get("data", {}).get("messages", [])
    if not any(row.get("id") == message_id for row in rows if isinstance(row, dict)):
        raise DrillFailure("first holder missed role mail queued before binding")
    return {
        "holder": holder,
        "role_key": f"builder:{plan_id}",
        "message_id": message_id,
        "queued_before_binding": True,
        "read_via_cli": True,
        "session": f"first-holder-{run_id}",
    }


def verify_single_claim(working: Path, run_id: str) -> dict[str, Any]:
    from varde_data.errors import Conflict
    from varde_data.queue import open_queue, open_slots
    from varde_data.records.queue import QueueItemInput

    queue_name = f"live-verify/{run_id}"
    plan_id = f"lv{run_id}claim"
    item_id = f"live-verify-{run_id}"
    queue = open_queue(working)
    slots = open_slots(working)
    queue.enqueue(
        QueueItemInput(
            id=item_id,
            plan_dir=str(working / "plans" / plan_id),
            role="builder",
            queue_name=queue_name,
            extra={"title": "Scratch role inbox claim"},
        )
    )
    holders = [f"lv{run_id}one-builder", f"lv{run_id}two-builder"]
    registered = [
        slots.register(
            holder,
            plan_id=plan_id,
            role="builder",
            agent_ref=f"verify-{run_id}-{index}",
            session_id=f"session-{run_id}-{index}",
            lease_s=3600,
        )
        for index, holder in enumerate(holders, start=1)
    ]

    claim_at = datetime.now(UTC)

    def claim(index: int, now: str | None = None) -> Any:
        return slots.claim(
            holders[index],
            epoch=registered[index].epoch,
            queue_name=queue_name,
            lease_s=1,
            now=now,
            ready=lambda _candidate, _in_flight: True,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda index: claim(index, claim_at.isoformat()), (0, 1))
        )
    item = one_claim(
        [
            None
            if result is None
            else {
                "id": result.id,
                "state": result.state,
                "claim_expires_at": result.claim_expires_at,
                "claim_generation": result.claim_generation,
                "claim_epoch": result.claim_epoch,
            }
            for result in results
        ]
    )
    if item["id"] != item_id:
        raise DrillFailure(f"claim returned an unexpected item: {item}")
    if not item["claim_expires_at"] or not item["claim_generation"]:
        raise DrillFailure(f"claim did not establish a lease: {item}")
    owner_index = next(
        index for index, result in enumerate(results) if result is not None
    )
    try:
        slots.claim(
            holders[owner_index],
            epoch=registered[owner_index].epoch + 1,
            queue_name=queue_name,
            lease_s=45,
        )
    except Conflict:
        fenced = True
    else:
        fenced = False
    if not fenced:
        raise DrillFailure("stale slot epoch was not fenced")
    expiry = (claim_at + timedelta(seconds=2)).isoformat()
    expired_items = queue.expire(expiry, workers=[holders[owner_index]])
    if len(expired_items) != 1:
        raise DrillFailure(f"expired claim was not requeued: {expired_items}")
    requeued = queue.get(queue_name, item_id)
    if requeued.state != "queued":
        raise DrillFailure(f"expired claim was not returned to queue: {requeued}")
    replacement_index = 1 - owner_index
    replacement = slots.claim(
        holders[replacement_index],
        epoch=registered[replacement_index].epoch,
        queue_name=queue_name,
        lease_s=45,
        now=expiry,
        ready=lambda _candidate, _in_flight: True,
    )
    if replacement is None or replacement.claim_generation <= item["claim_generation"]:
        raise DrillFailure(f"requeue did not advance claim generation: {replacement}")
    try:
        slots.finish(
            holders[replacement_index],
            epoch=registered[replacement_index].epoch,
            queue_name=queue_name,
            item_id=item_id,
            generation=item["claim_generation"],
        )
    except Conflict:
        stale_generation_fenced = True
    else:
        stale_generation_fenced = False
    if not stale_generation_fenced:
        raise DrillFailure("stale claim generation was accepted after requeue")
    return {
        "item_id": item_id,
        "claim_count": sum(result is not None for result in results),
        "holder": holders[owner_index],
        "lease_seconds": 1,
        "claim_generation": item["claim_generation"],
        "claim_epoch": item["claim_epoch"],
        "stale_epoch_fenced": fenced,
        "requeued_generation": requeued.claim_generation,
        "replacement_generation": replacement.claim_generation,
        "stale_generation_fenced": stale_generation_fenced,
    }


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def runner_command(port: int) -> list[str]:
    bootstrap = "from varde_runner import main; main()"
    return [
        sys.executable,
        "-c",
        bootstrap,
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]


def start_runner(env: dict[str, str], logs: Path, port: int) -> subprocess.Popen[str]:
    logs.parent.mkdir(parents=True, exist_ok=True)
    stream = logs.open("a", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell, isolated workdir.
        runner_command(port),
        cwd=REPO_ROOT,
        env=env,
        stdout=stream,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    stream.close()
    wait_for_runner(process, port)
    return process


def wait_for_runner(process: subprocess.Popen[str], port: int) -> None:
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + RUNNER_START_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise DrillFailure(f"scratch runner exited early ({process.returncode})")
        try:
            request = Request(f"http://127.0.0.1:{port}/api/degraded")
            with opener.open(request, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise DrillFailure("scratch runner did not become ready on its loopback port")


def stop_runner(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def verify_restart(
    working: Path, env: dict[str, str], log_path: Path
) -> dict[str, Any]:
    from varde_data.messages import open_messages
    from varde_data.store_mode import read_store_mode

    port = free_port()
    process = start_runner(env, log_path, port)
    try:
        version = open_messages(working, "sqlite").version()
    finally:
        stop_runner(process)
    log = log_path.read_text(encoding="utf-8")
    assert_clean_restart(log)
    mode = read_store_mode(working)
    if mode is None or (mode.primary, mode.mirror) != ("sqlite", "none"):
        raise DrillFailure(f"unexpected message mode after restart: {mode}")
    return {"port": port, "ready": True, "message_store_version": version}


def verify_rollback(
    working: Path,
    env: dict[str, str],
    read_holder: str,
    unread_holder: str,
    role_key: str,
) -> dict[str, Any]:
    from varde_data.backends.files.messages import FilesMessages
    from varde_data.backends.mirror.messages import MirrorMessages
    from varde_data.messages import open_messages
    from varde_data.role_inbox import select_role_inbox
    from varde_data.store_mode import set_store_mode

    marker = select_role_inbox(working)
    if marker is None:
        raise DrillFailure("role inbox was unavailable before rollback")
    marker.add_holder(role_key, role_key, live_holders=(role_key,))
    for row in open_messages(working, "sqlite").read_all().records:
        if row.to == role_key and row.id is not None:
            marker.ack(role_key, role_key, row.id)
    message_id = send_role_mail(working, env, "rollback-independent-cursor")
    read_result = command(
        ["msg", "read", "--as", read_holder, "--json"], working=working, env=env
    )
    read_payload = json.loads(read_result.stdout)
    read_rows = read_payload.get("data", {}).get("messages", [])
    if not any(
        row.get("id") == message_id for row in read_rows if isinstance(row, dict)
    ):
        raise DrillFailure("rollback broadcast was not read by its first holder")
    before = [
        row.id for row in marker.unread(role_key, unread_holder) if row.id is not None
    ]
    if message_id not in before:
        raise DrillFailure(f"rollback mail was not unread before flip: {before}")
    if message_id in {
        row.id for row in marker.unread(role_key, read_holder) if row.id is not None
    }:
        raise DrillFailure("first holder did not advance its independent cursor")
    set_store_mode(working, "mirror-sqlite")
    if not MirrorMessages(working, "sqlite", "files").sync():
        raise DrillFailure("SQLite-to-files mirror sync failed during rollback")
    set_store_mode(working, "mirror-files")
    set_store_mode(working, "files")
    from varde_data.backends.files.slots_reader import SlotReader

    files = FilesMessages(working, resolver=SlotReader(working))
    after = [row.id for row in files.peek_unread(role_key) if row.id is not None]
    identical = same_unread_set(before, after)
    if not identical or message_id not in after:
        raise DrillFailure(
            f"rollback changed unread role message set: before={before}, after={after}"
        )
    return {
        "read_holder": read_holder,
        "unread_holder": unread_holder,
        "role_key": role_key,
        "role_unread_before": sorted(before),
        "files_unread_after": sorted(after),
        "message_id": message_id,
        "identical": identical,
    }


def run_drill(source: Path, temp_root: Path) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:8]
    working = temp_root / "working-copy"
    scratch = temp_root / "scratch"
    config = scratch / "config"
    state = scratch / "state"
    home = scratch / "home"
    for directory in (config, state, home):
        directory.mkdir(parents=True, exist_ok=True)
    source_before = tree_digest(source, VOLATILE_SOURCE_PATHS)
    shutil.copytree(source, working, symlinks=True)
    source_after = tree_digest(source, VOLATILE_SOURCE_PATHS)
    copy_digest = tree_digest(working, VOLATILE_SOURCE_PATHS)
    if source_after != copy_digest:
        raise DrillFailure(
            "copied working directory differs from the post-copy source checksum"
        )
    env = runner_environment(working, config, state, home)
    backup_copied_inbox(working, temp_root / "inbox-backup")
    reset_copied_inbox(working)
    import_report = ensure_message_sqlite(working, env)
    activate_sqlite_mail(working)
    require_sqlite_queue(working)
    checks: dict[str, Any] = {
        "copy_consistency": {
            "source_before_sha256": source_before,
            "source_after_sha256": source_after,
            "copy_sha256": copy_digest,
            "source_changed_during_copy": source_before != source_after,
            "volatile_paths_omitted": sorted(VOLATILE_SOURCE_PATHS),
            "verified": True,
        },
        "message_import": import_report,
    }
    checks["successor_inherits"] = verify_successor(working, env, run_id)
    holders = [
        add_holder(working, f"lv{run_id}one", f"holder-one-{run_id}"),
        add_holder(working, f"lv{run_id}two", f"holder-two-{run_id}"),
    ]
    checks["delivery_and_cursors"] = verify_delivery_and_cursors(
        working, env, holders, run_id
    )
    checks["single_claim"] = verify_single_claim(working, run_id)
    first_holder = verify_first_holder_mail(working, env, run_id)
    checks["first_holder_queued_mail"] = first_holder
    checks["runner_restart"] = verify_restart(working, env, scratch / "runner.log")
    checks["rollback"] = verify_rollback(
        working,
        env,
        holders[0],
        holders[1],
        "builder",
    )
    return {"run_id": run_id, "working_copy": str(working), "checks": checks}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--keep-scratch", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.expanduser().resolve()
    if not source.is_dir():
        raise SystemExit(f"source working directory does not exist: {source}")
    if args.keep_scratch:
        temp_root = args.keep_scratch.expanduser().resolve()
        temp_root.mkdir(parents=True, exist_ok=False)
        report = run_drill(source, temp_root)
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 0
    with tempfile.TemporaryDirectory(prefix="varde-role-inbox-") as directory:
        report = run_drill(source, Path(directory))
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
