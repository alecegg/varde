from __future__ import annotations

import multiprocessing
import os
import queue
import random
import shutil
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import pytest
from varde_data.backends.mirror.messages import MirrorMessages
from varde_data.backends.sqlite.messages import factory
from varde_data.errors import Locked
from varde_data.messages import messages_db_path, open_messages
from varde_data.records.messages import Delivery, Message, NewMessage
from varde_data.store_mode import (
    StoreModeInvalid,
    _mark_import_verified,
    mirror_lag,
    read_store_mode,
    set_store_mode,
)

pytestmark = pytest.mark.slow


def _enter_worker_cwd(cwd: str, working: str) -> None:
    os.chdir(cwd)
    assert messages_db_path(Path(working)).is_file()


def _mode_for(working: str) -> str:
    record = read_store_mode(Path(working))
    if record is None:
        raise AssertionError("store mode marker is missing")
    return "mirror-files" if record.primary == "files" else "mirror-sqlite"


def _writer(
    working: str,
    start: int,
    count: int,
    cwd: str,
    ready: Any,
    written: Any,
) -> None:
    _enter_worker_cwd(cwd, working)
    ready.put(True)
    for index in range(start, start + count):
        for reader in ("reader-0", "reader-1"):
            repository = factory(Path(working))
            message = repository.append(
                NewMessage("writer", reader, "info", str(index), ts=str(index))
            )
            written.put((reader, message.id))


def _reader(
    working: str, reader: str, count: int, cwd: str, ready: Any, delivered: Any
) -> None:
    _enter_worker_cwd(cwd, working)
    ready.put(True)
    repository = factory(Path(working))
    batch = repository.claim_unread(reader, "session", "hook", "stress")
    seen: list[str] = []
    for message in batch:
        message_id = message.id or ""
        seen.append(message_id)
        delivered.put((reader, message_id))
        ack_repository = factory(Path(working))
        ack_repository.ack(reader, message_id, now="stress")
    assert len(seen) == count, f"{reader} claimed {len(seen)} of {count} messages"


def _poller(working: str, cwd: str, stop: Any, result: Any) -> None:
    _enter_worker_cwd(cwd, working)
    repository = factory(Path(working), busy_timeout=0.1)
    versions: list[int] = []
    pending_counts: list[int] = []
    while not stop.is_set():
        try:
            repository.status()
            pending = repository.pending_by_address()
            pending_counts.append(sum(map(len, pending.values())))
            versions.append(cast("int", repository.version().value))
        except Locked:
            pass
        stop.wait(0.003)
    repository = factory(Path(working), busy_timeout=0.1)
    repository.status()
    pending = repository.pending_by_address()
    pending_counts.append(sum(map(len, pending.values())))
    versions.append(cast("int", repository.version().value))
    result.put((versions, pending_counts))


def test_multiprocess_writers_readers_and_status_poller(  # noqa: PLR0915 - phases
    tmp_path: Path,
) -> None:
    _mark_import_verified(tmp_path, verified_at="2026-10-24T00:00:00Z")
    _enable_sqlite(tmp_path)
    reader_count = 2 * 8
    seed = factory(tmp_path)
    seed.register_reader("reader-0", from_start=True)
    seed.register_reader("reader-1", from_start=True)
    context = multiprocessing.get_context("spawn")
    worker_cwd = tmp_path / "different-cwd"
    worker_cwd.mkdir()
    ready = context.Queue()
    written = context.Queue()
    delivered = context.Queue()
    poll_result = context.Queue()
    stop_poller = context.Event()
    writers = [
        context.Process(
            target=_writer,
            args=(str(tmp_path), index * 8, 8, str(worker_cwd), ready, written),
        )
        for index in range(2)
    ]
    poller = context.Process(
        target=_poller, args=(str(tmp_path), str(worker_cwd), stop_poller, poll_result)
    )
    poller.start()
    for process in writers:
        process.start()
    for _ in writers:
        assert ready.get(timeout=10)
    written_rows = []
    write_deadline = time.monotonic() + 8
    while len(written_rows) < 2 * 8 * 2 and time.monotonic() < write_deadline:
        try:
            written_rows.append(written.get(timeout=0.2))
        except queue.Empty:
            continue
    for process in writers:
        process.join(2)
        if process.is_alive():
            process.terminate()
            process.join(2)
        assert process.exitcode == 0, f"writer stopped after {len(written_rows)} rows"

    readers = [
        context.Process(
            target=_reader,
            args=(
                str(tmp_path),
                f"reader-{index}",
                reader_count,
                str(worker_cwd),
                ready,
                delivered,
            ),
        )
        for index in range(2)
    ]
    for process in readers:
        process.start()
    for _ in readers:
        assert ready.get(timeout=10)
    delivered_rows = []
    reader_deadline = time.monotonic() + 8
    while len(delivered_rows) < reader_count * 2 and time.monotonic() < reader_deadline:
        try:
            delivered_rows.append(delivered.get(timeout=0.2))
        except queue.Empty:
            continue
    for process in readers:
        process.join(2)
        if process.is_alive():
            process.terminate()
            process.join(2)
        assert process.exitcode == 0, f"reader returned {len(delivered_rows)} claims"
    stop_poller.set()
    poll_result_rows = poll_result.get(timeout=5)
    poller.join(3)
    if poller.is_alive():
        poller.terminate()
        poller.join(2)
        pytest.fail("poller did not stop after its shutdown event")
    assert poller.exitcode == 0

    expected_by_reader = {
        reader: {
            message_id
            for target_reader, message_id in written_rows
            if target_reader == reader
        }
        for reader in ("reader-0", "reader-1")
    }
    for reader in ("reader-0", "reader-1"):
        ids = [
            message_id
            for target_reader, message_id in delivered_rows
            if target_reader == reader
        ]
        assert len(ids) == len(set(ids)) == reader_count
        assert set(ids) == expected_by_reader[reader]

    versions, pending_counts = poll_result_rows
    assert versions == sorted(versions)
    assert pending_counts[-1] == 0
    repository = factory(tmp_path)
    for reader in ("reader-0", "reader-1"):
        hook_unread = len(repository.claim_unread(reader, "verify", "hook", "stress"))
        cli_unread = len(repository.unread(reader))
        runner_unread = len(repository.pending_by_address().get(reader, ()))
        assert hook_unread == cli_unread == runner_unread == 0
    assert repository.status().lag == 0


def test_subprocess_resolves_store_from_other_cwd(tmp_path: Path) -> None:
    _mark_import_verified(tmp_path, verified_at="2026-10-24T00:00:00Z")
    script = (
        "from pathlib import Path; from varde_data.backends.sqlite.messages "
        "import factory, messages_db_path; import sys; "
        "p=Path(sys.argv[1]); r=factory(p); "
        "r.append(__import__('varde_data.records.messages', fromlist=['NewMessage'])"
        ".NewMessage('a','b','info','child',ts='t')); "
        "print(messages_db_path(p))"
    )
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    result = subprocess.run(  # noqa: S603 - fixed test script and temporary path
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=other_cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    assert Path(result.stdout.strip()) == messages_db_path(tmp_path)
    assert factory(tmp_path).read_all().records[0].text == "child"


def test_write_lock_exposes_only_documented_locked(tmp_path: Path) -> None:
    repo = factory(tmp_path, busy_timeout=0.03)
    repo.append(NewMessage("a", "b", "info", "seed", ts="0"))
    lock_path = messages_db_path(tmp_path)
    holder = subprocess.Popen(  # noqa: S603 - fixed lock-holder script
        [
            sys.executable,
            "-c",
            (
                "import sqlite3,sys,time; d=sqlite3.connect(sys.argv[1]); "
                "d.execute('BEGIN IMMEDIATE'); print('locked',flush=True); "
                "time.sleep(2)"
            ),
            str(lock_path),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(Locked):
            repo.append(NewMessage("a", "b", "info", "blocked", ts="1"))
    finally:
        holder.kill()
        holder.wait(timeout=3)


def test_killed_writer_reopens_consistently_and_version_never_reverses(
    tmp_path: Path,
) -> None:
    _mark_import_verified(tmp_path, verified_at="2026-10-24T00:00:00Z")
    _enable_sqlite(tmp_path)
    randomizer = random.Random(8108)  # noqa: S311 - deterministic stress timing
    observed_completed = 0
    cycles_with_rows = 0
    versions = [cast("int", factory(tmp_path).version().value)]

    for cycle in range(3):
        script = (
            "from pathlib import Path; import sys,time; "
            "from varde_data.messages import open_messages; "
            "from varde_data.records.messages import NewMessage; "
            "r=open_messages(Path(sys.argv[1]),'sqlite'); "
            "r.append(NewMessage('a','reader','info',"
            "f'seed-{sys.argv[2]}',ts='seed')); "
            "print('ready',flush=True); "
            "[(r.append(NewMessage('a','reader','info',"
            "f'{sys.argv[2]}-{i}',ts=str(i))),print('written',flush=True),"
            "time.sleep(.01)) for i in range(100)]"
        )
        child = subprocess.Popen(  # noqa: S603 - fixed test script and temporary path
            [sys.executable, "-c", script, str(tmp_path), str(cycle)],
            stdout=subprocess.PIPE,
            text=True,
        )
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        time.sleep(randomizer.uniform(0.025, 0.06))
        os.kill(child.pid, signal.SIGKILL)
        child.wait(timeout=5)
        observed_completed += child.stdout.read().count("written") + 1
        reopened = factory(tmp_path)
        rows = reopened.read_all().records
        cycle_rows = [
            row
            for row in rows
            if row.text.startswith(f"{cycle}-") or row.text == f"seed-{cycle}"
        ]
        cycles_with_rows += bool(cycle_rows)
        current = cast("int", reopened.version().value)
        assert current >= versions[-1]
        versions.append(current)
        assert len({row.id for row in rows}) == len(rows)
        assert all(row.id for row in rows)

    batch_size = 400
    batch_script = (
        "import sqlite3,sys,time; "
        "db=sqlite3.connect(sys.argv[1]); db.execute('BEGIN IMMEDIATE'); "
        "sql='INSERT INTO messages(id,legacy_id,ts,sender,recipient,kind,body,notes) "
        "VALUES(?,?,?,?,?,?,?,?)'; "
        "[(db.execute(sql,(f'batch-{i}',None,str(i),'a','reader',"
        "'info','batch',None)), "
        "print('batch-open',flush=True) if i==50 else None, time.sleep(.002)) "
        "for i in range(400)]; db.commit()"
    )
    child = subprocess.Popen(  # noqa: S603 - fixed transaction script and temp database
        [sys.executable, "-c", batch_script, str(messages_db_path(tmp_path))],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "batch-open"
    time.sleep(randomizer.uniform(0.01, 0.03))
    os.kill(child.pid, signal.SIGKILL)
    child.wait(timeout=5)
    reopened = factory(tmp_path)
    batch_rows = [
        row
        for row in reopened.read_all().records
        if row.id and row.id.startswith("batch-")
    ]
    assert len(batch_rows) in {0, batch_size}
    assert cycles_with_rows >= 2
    assert len(reopened.read_all().records) >= observed_completed
    final_version = cast("int", reopened.version().value)
    assert final_version >= versions[-1]


def test_cutover_flips_under_writer_and_hook_reader_load(  # noqa: PLR0915 - phases
    tmp_path: Path,
) -> None:
    _mark_import_verified(tmp_path, verified_at="2026-10-24T00:00:00Z")
    set_store_mode(tmp_path, "mirror-files")
    seed = cast("MirrorMessages", open_messages(tmp_path, "mirror-files"))
    for reader in ("reader-0", "reader-1"):
        seed.register_reader(reader, from_start=True)

    context = multiprocessing.get_context("spawn")
    worker_cwd = tmp_path / "cutover-cwd"
    worker_cwd.mkdir()
    ready = context.Queue()
    written = context.Queue()
    worker_events = context.Queue()
    observed_events: list[tuple[Any, ...]] = []
    stop_workers = context.Event()
    work_queues = {
        reader: context.Queue(maxsize=8) for reader in ("reader-0", "reader-1")
    }
    writer = context.Process(
        target=_cutover_writer,
        args=(
            str(tmp_path),
            str(worker_cwd),
            work_queues,
            ready,
            written,
            stop_workers,
        ),
    )
    readers = [
        context.Process(
            target=_cutover_reader,
            args=(
                str(tmp_path),
                str(worker_cwd),
                reader,
                work_queues[reader],
                ready,
                worker_events,
            ),
        )
        for reader in ("reader-0", "reader-1")
    ]
    writer.start()
    for process in readers:
        process.start()

    observed_writes: list[tuple[str, str, str]] = []
    try:
        for _ in range(3):
            assert ready.get(timeout=10)
        _collect_writes_until(
            written,
            observed_writes,
            lambda rows: len(rows) >= 8,
            worker_events,
            observed_events,
        )
        flip_attempts = [_flip_while_workers_run(tmp_path, "mirror-sqlite", writer)]
        _collect_writes_until(
            written,
            observed_writes,
            lambda rows: sum(mode == "mirror-sqlite" for _, _, mode in rows) >= 8,
            worker_events,
            observed_events,
        )
        flip_attempts.append(_flip_while_workers_run(tmp_path, "mirror-files", writer))
        _collect_writes_until(
            written,
            observed_writes,
            lambda rows: sum(mode == "mirror-files" for _, _, mode in rows) >= 8,
            timeout=5,
            worker_events=worker_events,
            observed_events=observed_events,
        )
    finally:
        stop_workers.set()
        shutdown_deadline = time.monotonic() + 20
        workers = (writer, *readers)
        while time.monotonic() < shutdown_deadline and any(
            process.is_alive() for process in workers
        ):
            observed_writes.extend(_drain_queue(written))
            observed_events.extend(_drain_queue(worker_events))
            for process in workers:
                process.join(0.02)
        for process in workers:
            if process.is_alive():
                process.terminate()
                process.join(2)

    observed_writes.extend(_drain_queue(written))
    observed_events.extend(_drain_queue(worker_events))
    assert writer.exitcode == 0, writer.exitcode
    assert all(process.exitcode == 0 for process in readers), (
        [process.exitcode for process in readers],
        observed_events,
    )
    assert all(event[0] in {"claim", "ack"} for event in observed_events), (
        observed_events
    )
    observed_claims = [
        (reader, message_id)
        for kind, reader, message_id in observed_events
        if kind == "claim"
    ]
    observed_acks = [
        (reader, message_id)
        for kind, reader, message_id in observed_events
        if kind == "ack"
    ]
    written_pairs = [(reader, message_id) for reader, message_id, _ in observed_writes]
    assert len(written_pairs) == len(set(written_pairs))
    assert len(observed_claims) == len(set(observed_claims))
    assert set(observed_claims) == set(written_pairs)
    assert len(observed_acks) == len(set(observed_acks))
    assert set(observed_acks) == set(written_pairs)

    repository = cast("MirrorMessages", open_messages(tmp_path, "mirror-files"))
    assert repository.sync()
    assert repository.compare()
    assert mirror_lag(tmp_path, verify=True) == 0
    for primary, mirror in ((repository.primary, repository.mirror),):
        for store in (primary, mirror):
            events = store.deliveries()
            acked_pairs = {
                (delivery.reader, delivery.message_id)
                for delivery in events
                if delivery.event == "acked"
            }
            assert acked_pairs == set(written_pairs)
    assert len(flip_attempts) == 2 and all(attempts > 0 for attempts in flip_attempts)


def _cutover_writer(
    working: str,
    cwd: str,
    work_queues: dict[str, Any],
    ready: Any,
    written: Any,
    stop: Any,
) -> None:
    _enter_worker_cwd(cwd, working)
    ready.put(True)
    try:
        for index in range(1000):
            if stop.is_set():
                return
            for reader, work_queue in work_queues.items():
                mode = _mode_for(working)
                repository = open_messages(Path(working), mode)
                message = repository.append(
                    NewMessage(
                        "writer", reader, "info", f"cutover-{index}", ts=str(index)
                    )
                )
                written.put((reader, message.id, mode))
                work_queue.put((reader, message.id))
            stop.wait(0.02)
    finally:
        for work_queue in work_queues.values():
            work_queue.put(None)


def _cutover_reader(
    working: str,
    cwd: str,
    reader: str,
    work_queue: Any,
    ready: Any,
    events: Any,
) -> None:
    _enter_worker_cwd(cwd, working)
    ready.put(True)
    while True:
        notice = work_queue.get()
        if notice is None:
            return
        try:
            mode = _mode_for(working)
            repository = open_messages(Path(working), mode)
            if not repository.peek_unread(reader):
                continue
            for message in repository.claim_unread(reader, "hook", "hook", "stress"):
                message_id = message.id or ""
                events.put(("claim", reader, message_id))
                ack_repository = open_messages(Path(working), _mode_for(working))
                ack_repository.ack(reader, message_id, now="stress")
                events.put(("ack", reader, message_id))
        except Exception as exc:
            events.put(("error", reader, repr(exc)))
            raise


def _collect_writes_until(
    written: Any,
    observed: list[tuple[str, str, str]],
    predicate: Any,
    worker_events: Any,
    observed_events: list[tuple[Any, ...]],
    *,
    timeout: float = 5,
) -> None:
    deadline = time.monotonic() + timeout
    while not predicate(observed) and time.monotonic() < deadline:
        while True:
            try:
                event = worker_events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "error":
                raise AssertionError(f"cutover reader failed: {event}")
            observed_events.append(event)
        try:
            row = written.get(timeout=0.25)
        except queue.Empty:
            continue
        observed.append(row)
    assert predicate(observed), "writer did not reach the requested cutover phase"


def _drain_queue(source: Any) -> list[Any]:
    rows = []
    while True:
        try:
            rows.append(source.get_nowait())
        except queue.Empty:
            return rows


def _flip_while_workers_run(working: Path, target: str, writer: Any) -> int:
    deadline = time.monotonic() + 10
    attempts = 0
    while time.monotonic() < deadline:
        assert writer.is_alive(), "writer stopped before the requested mode flip"
        mode = _mode_for(str(working))
        repository = cast("MirrorMessages", open_messages(working, mode))
        repository.sync()
        attempts += 1
        try:
            set_store_mode(working, target)  # type: ignore[arg-type]
        except StoreModeInvalid as exc:
            if "mirror lag is nonzero" not in str(exc):
                raise
            time.sleep(0.01)
            continue
        return attempts
    raise AssertionError(
        f"could not flip to {target} while workers were active "
        f"after {attempts} attempts"
    )


def _prepare_latency_fixture(
    working: Path,
    message_count: int,
    delivery_count: int,
    mode: str,
    *,
    unread_count: int = 1,
) -> Any:
    _mark_import_verified(working, verified_at="2026-10-24T00:00:00Z")
    set_store_mode(working, "mirror-files")
    if mode == "mirror-sqlite":
        set_store_mode(working, mode)
    elif mode == "sqlite":
        set_store_mode(working, "mirror-sqlite")
        set_store_mode(working, mode)
    elif mode == "files":
        set_store_mode(working, "files")
    repository: Any = open_messages(working, mode)
    historical_count = message_count - unread_count
    if historical_count < 1:
        raise ValueError("latency fixture requires at least one historical message")
    messages = tuple(
        Message(
            str(index), "sender", "reader", "info", str(index), id=f"stress-{index:08}"
        )
        for index in range(message_count)
    )
    primary = repository.primary if hasattr(repository, "primary") else repository
    primary.import_messages(messages)
    primary.import_deliveries(
        tuple(
            Delivery(
                messages[index % historical_count].id or "",
                "reader",
                f"old-{index}",
                "hook",
                "delivered" if index < historical_count else "acked",
                "stress",
            )
            for index in range(delivery_count)
        )
    )
    if hasattr(repository, "sync"):
        assert repository.sync()
    repository.register_reader("reader", from_start=True)
    if hasattr(repository, "sync"):
        assert repository.sync()
    return repository


def _measure_hook_path(working: Path, mode: str, count: int) -> float:
    started = time.perf_counter()
    repository = open_messages(working, mode)
    rows = repository.claim_unread("reader", "session", "hook", "stress")
    elapsed = (time.perf_counter() - started) * 1000
    assert len(rows) == 1
    return elapsed


def _measure_hook_subprocess(working: Path, mode: str, expected: int = 1) -> float:
    script = """
import sys, time
started = time.perf_counter()
from pathlib import Path
from varde_data.messages import open_messages
repository = open_messages(Path(sys.argv[1]), sys.argv[2])
rows = repository.claim_unread('reader', 'session', 'hook', 'stress')
assert len(rows) == int(sys.argv[3]), len(rows)
print((time.perf_counter() - started) * 1000)
"""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script, str(working), mode, str(expected)],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    return float(result.stdout.strip())


def _copy_latency_fixture(source: Path, destination: Path) -> None:
    source_inbox = source / ".cache/inbox"
    destination_inbox = destination / ".cache/inbox"
    destination_inbox.parent.mkdir(parents=True)
    shutil.copytree(source_inbox, destination_inbox)


def test_hook_latency_500_messages_all_store_modes(tmp_path: Path) -> None:
    for mode in ("sqlite", "mirror-files", "mirror-sqlite"):
        template = tmp_path / mode / "template"
        _prepare_latency_fixture(template, 500, 998, mode)
        samples: list[float] = []
        for index in range(6):
            working = tmp_path / mode / f"sample-{index}"
            _copy_latency_fixture(template, working)
            samples.append(_measure_hook_path(working, mode, 500))
        measured = samples[1:]
        median = statistics.median(measured)
        assert median < 70, (
            f"{mode} open+claim median of five took {median:.1f} ms for 500 messages; "
            f"warm-up={samples[0]:.1f} ms, measured="
            f"{[round(sample, 1) for sample in measured]} ms"
        )


def test_latency_fixture_counts_messages_and_deliveries_separately(
    tmp_path: Path,
) -> None:
    repository = _prepare_latency_fixture(tmp_path / "working", 7, 12, "sqlite")

    assert len(repository.read_all().records) == 7
    assert len(repository.deliveries()) == 12


def test_hook_latency_production_size_fixture(tmp_path: Path) -> None:
    if os.environ.get("VARDE_STRESS_LIVE_SIZE") != "1":
        pytest.skip("set VARDE_STRESS_LIVE_SIZE=1 for the live-shaped timing run")
    message_count = 3_067
    delivery_count = 32_744
    unread_count = 3
    results: dict[str, float] = {}
    samples_by_mode: dict[str, list[float]] = {}
    for mode in ("files", "sqlite", "mirror-files", "mirror-sqlite"):
        template = tmp_path / mode / "template"
        _prepare_latency_fixture(
            template,
            message_count,
            delivery_count,
            mode,
            unread_count=unread_count,
        )
        samples = []
        for index in range(5):
            working_copy = tmp_path / mode / f"sample-{index}"
            _copy_latency_fixture(template, working_copy)
            samples.append(
                _measure_hook_subprocess(working_copy, mode, expected=unread_count)
            )
        elapsed = statistics.median(samples)
        results[mode] = elapsed
        samples_by_mode[mode] = samples
    files_baseline = results["files"]
    mirror_files_limit = max(70, files_baseline * 1.25) if files_baseline >= 70 else 70
    print(
        f"fresh-process open+claim median ms ({message_count} messages, "
        f"{delivery_count} deliveries, {unread_count} unread): "
        + ", ".join(
            f"{mode}={value:.1f} samples="
            f"{[round(sample, 1) for sample in samples_by_mode[mode]]}"
            for mode, value in results.items()
        ),
        flush=True,
    )
    assert results["sqlite"] < 70, (
        f"sqlite fresh-process open+claim median {results['sqlite']:.1f} ms "
        f"for {message_count} messages and {delivery_count} deliveries"
    )
    assert results["mirror-sqlite"] < 70, (
        f"mirror-sqlite fresh-process open+claim median "
        f"{results['mirror-sqlite']:.1f} ms for {message_count} messages and "
        f"{delivery_count} deliveries"
    )
    assert results["mirror-files"] <= mirror_files_limit, (
        f"mirror-files {results['mirror-files']:.1f} ms exceeded files baseline "
        f"{files_baseline:.1f} ms or its {mirror_files_limit:.1f} ms limit"
    )


def _enable_sqlite(working: Path) -> None:
    set_store_mode(working, "mirror-files")
    set_store_mode(working, "mirror-sqlite")
    set_store_mode(working, "sqlite")
