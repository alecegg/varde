from __future__ import annotations

import multiprocessing
import time
from pathlib import Path
from typing import Any

from varde_core.frontmatter import parse
from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.errors import Locked
from varde_data.frontmatter_patch import patch_fields
from varde_data.locking import atomic_write
from varde_data.plan_state_sync import import_plan_dir
from varde_data.queue_md import parse_queue_md
from varde_data.queue_migrate import migrate
from varde_data.queue_mode_lock import barrier, operation
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_rollback import rollback
from varde_data.queue_store import initialize

FIXTURE = Path(__file__).parent / "fixtures/queue_md/ux-audit-fixes-1.md"


def _markdown_writer(
    root: str, output: Any, ready: Any, begin: Any, locked: Any
) -> None:
    working = Path(root)
    ready.set()
    begin.wait(timeout=5)
    retries = 0
    for index in range(8):
        while True:
            try:
                with operation(working, timeout=0.02) as mode:
                    if mode != "markdown":
                        time.sleep(0.005)
                        continue
                    plan = working / f"plans/markdown-{index:02d}/plan.md"
                    updated = patch_fields(
                        plan.read_bytes(), set_fields={"status": f"ack-{index}"}
                    )
                    atomic_write(plan, updated, mode=0o644)
                    output.put(("markdown", index, retries))
                    break
            except Locked:
                retries += 1
                locked.set()
                time.sleep(0.005)
        time.sleep(0.015)


def _sqlite_writer(root: str, output: Any, ready: Any, begin: Any, locked: Any) -> None:
    working = Path(root)
    repository = SQLiteQueue(working / QUEUE_DATABASE)
    ready.set()
    begin.wait(timeout=5)
    retries = 0
    for index in range(5):
        while True:
            try:
                with operation(working, timeout=0.02) as mode:
                    if mode != "sqlite":
                        time.sleep(0.005)
                        continue
                    repository.transition(
                        "plans/bundle/queue.md",
                        chr(ord("B") + index),
                        "building",
                        actor=f"sqlite-{index}",
                        expect_state="queued",
                    )
                    output.put(("sqlite", index, retries))
                    break
            except Locked:
                retries += 1
                locked.set()
                time.sleep(0.005)
        time.sleep(0.015)


def _working(root: Path) -> None:
    bundle = root / "plans/bundle"
    bundle.mkdir(parents=True)
    (bundle / "queue.md").write_text(FIXTURE.read_text())
    (bundle / "plan.md").write_text("---\nstatus: active\n---\n")
    for index in range(8):
        plan = root / f"plans/markdown-{index:02d}/plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("---\nstatus: active\n---\n")


def test_writes_survive_three_migrate_rollback_cycles(tmp_path: Path) -> None:
    root = tmp_path / "working"
    _working(root)
    initialize(root)
    import_plan_dir(root, root / "plans/bundle")

    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    markdown_ready, sqlite_ready = context.Event(), context.Event()
    begin = context.Event()
    markdown_locked, sqlite_locked = context.Event(), context.Event()
    writers = [
        context.Process(
            target=_markdown_writer,
            args=(str(root), output, markdown_ready, begin, markdown_locked),
        ),
        context.Process(
            target=_sqlite_writer,
            args=(str(root), output, sqlite_ready, begin, sqlite_locked),
        ),
    ]
    for writer in writers:
        writer.start()
    assert markdown_ready.wait(5) and sqlite_ready.wait(5)

    try:
        with barrier(root, timeout=5):
            begin.set()
            assert markdown_locked.wait(5)
            assert sqlite_locked.wait(5)
        for _ in range(3):
            migrate(root)
            time.sleep(0.04)
            rollback(root)
            time.sleep(0.04)

        for writer in writers:
            writer.join(20)
            assert writer.exitcode == 0
    finally:
        for writer in writers:
            if writer.is_alive():
                writer.terminate()
                writer.join(5)

    writes = [output.get(timeout=2) for _ in range(13)]
    assert sum(retries for _kind, _index, retries in writes) > 0
    markdown_writes = {(kind, index) for kind, index, _ in writes if kind == "markdown"}
    sqlite_writes = {(kind, index) for kind, index, _ in writes if kind == "sqlite"}
    assert markdown_writes == {("markdown", index) for index in range(8)}
    assert sqlite_writes == {("sqlite", index) for index in range(5)}

    for index in range(8):
        fields, _ = parse((root / f"plans/markdown-{index:02d}/plan.md").read_bytes())
        assert fields["status"] == f"ack-{index}"
    queue = parse_queue_md((root / "plans/bundle/queue.md").read_text())
    states = {row.values["id"]: row.values["state"] for row in queue.rows}
    assert all(states[chr(ord("B") + index)] == "building" for index in range(5))
