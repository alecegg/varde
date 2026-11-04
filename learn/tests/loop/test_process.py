from __future__ import annotations

import signal
import sys
import time
from pathlib import Path

import pytest
from varde_learn.loop.process import ExitResult, RunRequest, run_with_timeout


def _request(
    tmp_path: Path, code: str, *, stdin: bytes = b"", timeout: float = 3
) -> RunRequest:
    return RunRequest(
        sys.executable,
        ("-c", code),
        tmp_path,
        {},
        stdin,
        tmp_path / "stdout",
        tmp_path / "stderr",
        timeout,
    )


def test_timeout_kills_group_with_no_survivor(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    marker = tmp_path / "survived"
    child = (
        "from pathlib import Path\n"
        "import time\n"
        f"Path({str(ready)!r}).touch()\n"
        f"release = Path({str(release)!r})\n"
        "while not release.exists():\n"
        "    time.sleep(.01)\n"
        f"Path({str(marker)!r}).write_text('alive')"
    )
    code = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        f"ready = __import__('pathlib').Path({str(ready)!r})\n"
        "deadline = time.monotonic() + 2\n"
        "while not ready.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(.01)\n"
        "time.sleep(5)"
    )
    result = run_with_timeout(_request(tmp_path, code))
    assert result.timed_out
    assert result.result is None
    assert ready.exists()
    release.touch()
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.01)
    assert not marker.exists()


def test_successful_leader_exit_kills_remaining_group_members(tmp_path: Path) -> None:
    marker = tmp_path / "survived"
    child = f"import time; time.sleep(.2); open({str(marker)!r},'w').write('alive')"
    result = run_with_timeout(
        _request(
            tmp_path,
            f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}])",
        )
    )
    assert result.result is not None
    assert result.result.code == 0
    time.sleep(0.25)
    assert not marker.exists()


def test_timeout_covers_large_stdin_to_nonreader(tmp_path: Path) -> None:
    result = run_with_timeout(
        _request(
            tmp_path,
            "import time; time.sleep(5)",
            stdin=b"x" * (2 * 1024 * 1024),
            timeout=0.05,
        )
    )
    assert result.timed_out


def test_large_stdin_is_delivered_completely_and_closed(tmp_path: Path) -> None:
    result = run_with_timeout(
        _request(
            tmp_path,
            "import sys; sys.stdout.write(str(len(sys.stdin.buffer.read())))",
            stdin=b"x" * (2 * 1024 * 1024),
        )
    )
    assert result.result is not None
    assert result.result.code == 0
    assert (tmp_path / "stdout").read_text() == str(2 * 1024 * 1024)


def test_early_exit_with_large_stdin_preserves_exit_status(tmp_path: Path) -> None:
    result = run_with_timeout(
        _request(tmp_path, "raise SystemExit(7)", stdin=b"x" * (2 * 1024 * 1024))
    )
    assert result.result is not None
    assert result.result.code == 7


def test_interruption_during_stdin_delivery_kills_child_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from varde_learn.loop import process

    real_popen = process.subprocess.Popen
    marker = tmp_path / "survived"

    class InterruptingChild:
        def __init__(self, *args, **kwargs):
            self.child = real_popen(*args, **kwargs)
            self.pid = self.child.pid

        def communicate(self, *args, **kwargs):
            raise KeyboardInterrupt

        def wait(self):
            return self.child.wait()

    monkeypatch.setattr(process.subprocess, "Popen", InterruptingChild)
    script = f"import time; time.sleep(.2); open({str(marker)!r},'w').write('alive')"
    with pytest.raises(KeyboardInterrupt):
        run_with_timeout(
            _request(
                tmp_path,
                f"import subprocess,sys; "
                f"subprocess.Popen([sys.executable,'-c',{script!r}])",
            )
        )
    time.sleep(0.25)
    assert not marker.exists()


def test_timeout_normal_exit_status_propagates(tmp_path: Path) -> None:
    result = run_with_timeout(_request(tmp_path, "raise SystemExit(0)"))
    assert not result.timed_out
    assert result.result is not None
    assert result.result.as_shell_code() == 0


def test_timeout_signal_death_reports_128_plus_signal() -> None:
    result = ExitResult(-signal.SIGTERM)
    assert result.as_shell_code() == 128 + signal.SIGTERM
