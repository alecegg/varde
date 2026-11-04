from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys

from node_host_helpers import ECHO_ENGINE, HOST_SCRIPT, make_host, pid_alive, wait_until
from varde_runner.node_host import reap_orphans
from varde_runner.node_host.orphans import (
    GroupRecord,
    identify_group,
    read_record,
    write_record,
)

RUNNER_PROC = ECHO_ENGINE.parent / "runner_proc.py"


def test_runner_death_leaves_no_orphans(tmp_path) -> None:
    state = tmp_path / "host.json"
    runner = subprocess.Popen(  # noqa: S603 - fixed test helper.
        [
            sys.executable,
            str(RUNNER_PROC),
            str(HOST_SCRIPT),
            str(ECHO_ENGINE),
            str(state),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert runner.stdout is not None
        pids = json.loads(runner.stdout.readline())
        assert all(pid_alive(pid) for pid in pids.values())
        recorded = read_record(state)
        assert [group.process_group for group in recorded] == [
            pids["host"],
            pids["tracked_child"],
        ]
        runner.kill()
        runner.wait()
        assert wait_until(
            lambda: not any(pid_alive(pid) for pid in pids.values()), 15
        ), pids
    finally:
        runner.kill()
        runner.wait()


def spawn_stale_group() -> int:
    """Start a detached sleep that is not our child, so init reaps it."""
    code = (
        "import subprocess; d = subprocess.DEVNULL; "
        "p = subprocess.Popen(['sleep', '300'], start_new_session=True, "
        "stdin=d, stdout=d, stderr=d); print(p.pid)"
    )
    out = subprocess.run(  # noqa: S603 - fixed test helper.
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return int(out.stdout)


def test_runner_restart_reaps_stale_host_and_tracked_groups(tmp_path) -> None:
    host_pid, tracked_pid = spawn_stale_group(), spawn_stale_group()
    state = tmp_path / "host.json"
    write_record(
        state,
        identify_group(host_pid, host_pid, ["sleep", "300"]),
        [identify_group(tracked_pid, tracked_pid)],
    )
    assert pid_alive(host_pid)
    reaped = asyncio.run(reap_orphans(state))
    assert reaped == [host_pid, tracked_pid]
    assert wait_until(
        lambda: not pid_alive(host_pid) and not pid_alive(tracked_pid), 10
    )
    assert not state.exists()


def test_reap_skips_group_whose_identity_changed(tmp_path) -> None:
    pid = spawn_stale_group()
    state = tmp_path / "host.json"
    try:
        stale = GroupRecord(pid, pid, "Mon Jan  1 00:00:00 2001", ["sleep", "300"])
        write_record(state, stale, [])
        assert asyncio.run(reap_orphans(state)) == []
        assert pid_alive(pid)
    finally:
        os.killpg(pid, signal.SIGKILL)


def test_start_reaps_recorded_stale_group(tmp_path) -> None:
    pid = spawn_stale_group()
    state = tmp_path / "host.json"
    write_record(state, identify_group(pid, pid, ["sleep", "300"]), [])

    async def scenario() -> None:
        host = make_host(state_path=state)
        await host.start()
        try:
            assert wait_until(lambda: not pid_alive(pid), 10)
            assert [g.process_group for g in read_record(state)] == [host.pid]
        finally:
            await host.stop()
        assert not state.exists()

    asyncio.run(scenario())
