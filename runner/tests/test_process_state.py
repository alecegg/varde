import asyncio
from pathlib import Path

import pytest
from varde_runner.plugins.process_state import (
    ProcessIdentity,
    inspect_process,
    inspect_process_async,
    wait_for_group_exit,
)


def _fake_ps(tmp_path: Path, body: str) -> Path:
    executable = tmp_path / "ps"
    executable.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def test_inspect_process_keeps_configured_ps_arguments(tmp_path):
    args_path = tmp_path / "args"
    executable = _fake_ps(
        tmp_path,
        f"printf '%s\\n' \"$@\" > '{args_path}'\n"
        "printf 'Mon Jan  2 03:04:05 2006 python worker\\n'",
    )

    identity = inspect_process(123, "Test", executable=str(executable))

    assert identity == ProcessIdentity("Mon Jan 2 03:04:05 2006", "python worker")
    assert args_path.read_text(encoding="utf-8").splitlines() == [
        "-p",
        "123",
        "-o",
        "lstart=,command=",
    ]


def test_inspect_process_preserves_separate_output_options(tmp_path):
    args_path = tmp_path / "args"
    executable = _fake_ps(
        tmp_path,
        f"printf '%s\\n' \"$@\" > '{args_path}'\n"
        "printf 'Mon Jan  2 03:04:05 2006 python worker\\n'",
    )

    inspect_process(
        123,
        "OpenCode",
        executable=str(executable),
        output_args=("lstart=", "-o", "command="),
        on_error="none",
        timeout=None,
    )

    assert args_path.read_text(encoding="utf-8").splitlines() == [
        "-p",
        "123",
        "-o",
        "lstart=",
        "-o",
        "command=",
    ]


def test_inspect_process_async_reads_fake_ps(tmp_path, monkeypatch):
    args_path = tmp_path / "args"
    _fake_ps(
        tmp_path,
        f"printf '%s\\n' \"$@\" > '{args_path}'\n"
        "printf 'Mon Jan  2 03:04:05 2006 pi --rpc\\n'",
    )
    monkeypatch.setenv("PATH", str(tmp_path))

    assert asyncio.run(inspect_process_async(456, "Pi")) == ProcessIdentity(
        "Mon Jan 2 03:04:05 2006", "pi --rpc"
    )
    assert args_path.read_text(encoding="utf-8").splitlines() == [
        "-p",
        "456",
        "-o",
        "lstart=,command=",
    ]


def test_inspect_process_async_times_out_and_reaps_fake_ps(tmp_path, monkeypatch):
    _fake_ps(tmp_path, "exec /bin/sleep 5")
    monkeypatch.setenv("PATH", str(tmp_path))

    message = "ps timed out while inspecting Test process"
    with pytest.raises(RuntimeError, match=message):
        asyncio.run(inspect_process_async(789, "Test"))


def test_wait_for_group_exit_handles_exit_and_timeout():
    checks = 0

    def exits_after_one_check(_group: int) -> bool:
        nonlocal checks
        checks += 1
        return checks == 1

    async def check() -> None:
        assert await wait_for_group_exit(10, 1, exits_after_one_check, poll_interval=0)
        assert not await wait_for_group_exit(10, 0, lambda _group: True)

    asyncio.run(check())
