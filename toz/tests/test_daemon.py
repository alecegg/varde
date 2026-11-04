import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def runtime():
    directory = Path(tempfile.mkdtemp(prefix="tozrt-"))
    return {
        **os.environ,
        "XDG_RUNTIME_DIR": str(directory),
        "PYTHONPATH": str(ROOT / "src"),
    }


def payload(text="hello"):
    return json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "session_id": "daemon-test",
            "tool_name": "Bash",
            "tool_input": {"command": "echo test"},
            "tool_response": {"stdout": text, "stderr": "", "interrupted": False},
        }
    ).encode()


def wait_for_socket(path, process):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"daemon exited: {process.returncode}")
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError("daemon socket did not appear")


def test_client_matches_in_process_and_falls_back(tmp_path):
    env = runtime()
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.toml").write_text(
        '[hooks.post_tool_use]\nproviders=["capture","toz_note"]\nthreshold=4\n'
    )
    env["TOZ_CONFIG_DIR"] = str(config)
    env["CONFIG_DIR"] = str(config)
    env["VARDE_TOZ_DATA_DIR"] = str(tmp_path / "data")
    data = payload()
    direct = subprocess.run(
        [
            sys.executable,
            "-m",
            "varde_toz.cli",
            "hook",
            "post-tool-use",
            "--harness",
            "claude",
        ],
        input=data,
        stdout=subprocess.PIPE,
        env=env,
        cwd=ROOT,
        check=False,
    )
    fallback = subprocess.run(
        [
            sys.executable,
            "-m",
            "varde_toz.daemon.client",
            "hook",
            "post-tool-use",
            "--harness",
            "claude",
        ],
        input=data,
        stdout=subprocess.PIPE,
        env=env,
        cwd=ROOT,
        check=False,
    )
    assert fallback.returncode == direct.returncode == 0
    assert fallback.stdout == direct.stdout


@pytest.mark.usefixtures("unix_socket_bind")
def test_stale_socket_is_replaced_and_client_falls_back(tmp_path):
    env = runtime()
    runtime_dir = Path(env["XDG_RUNTIME_DIR"]) / "varde-toz"
    runtime_dir.mkdir(mode=0o700)
    path = runtime_dir / "hook.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(path))
    listener.close()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "varde_toz.daemon.client",
            "hook",
            "post-tool-use",
            "--harness",
            "claude",
        ],
        input=payload(),
        stdout=subprocess.PIPE,
        env=env,
        cwd=ROOT,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0


def test_client_falls_back_when_socket_path_cannot_be_bound(tmp_path):
    env = runtime()
    long_runtime = Path(tempfile.mkdtemp(prefix="r" * 88))
    env["XDG_RUNTIME_DIR"] = str(long_runtime)
    data = payload()
    direct = subprocess.run(
        [
            sys.executable,
            "-m",
            "varde_toz.cli",
            "hook",
            "post-tool-use",
            "--harness",
            "claude",
        ],
        input=data,
        stdout=subprocess.PIPE,
        env=env,
        cwd=ROOT,
        check=False,
    )
    client = subprocess.run(
        [
            sys.executable,
            "-m",
            "varde_toz.daemon.client",
            "hook",
            "post-tool-use",
            "--harness",
            "claude",
        ],
        input=data,
        stdout=subprocess.PIPE,
        env=env,
        cwd=ROOT,
        timeout=5,
        check=False,
    )
    assert client.returncode == direct.returncode == 0
    assert client.stdout == direct.stdout


@pytest.mark.usefixtures("unix_socket_bind")
def test_client_falls_back_when_daemon_closes_without_reply(tmp_path):
    env = runtime()
    directory = Path(env["XDG_RUNTIME_DIR"]) / "varde-toz"
    directory.mkdir(mode=0o700)
    path = directory / "hook.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(1)

    def close_without_reply():
        connection, _ = listener.accept()
        with connection:
            while connection.recv(4096):
                pass
        listener.close()

    import threading

    thread = threading.Thread(target=close_without_reply)
    thread.start()
    data = payload()
    direct = subprocess.run(
        [
            sys.executable,
            "-m",
            "varde_toz.cli",
            "hook",
            "post-tool-use",
            "--harness",
            "claude",
        ],
        input=data,
        stdout=subprocess.PIPE,
        env=env,
        cwd=ROOT,
        check=False,
    )
    client = subprocess.run(
        [
            sys.executable,
            "-m",
            "varde_toz.daemon.client",
            "hook",
            "post-tool-use",
            "--harness",
            "claude",
        ],
        input=data,
        stdout=subprocess.PIPE,
        env=env,
        cwd=ROOT,
        timeout=5,
        check=False,
    )
    thread.join(timeout=3)
    assert client.returncode == direct.returncode == 0
    assert client.stdout == direct.stdout


@pytest.mark.usefixtures("unix_socket_bind")
def test_client_recovers_after_daemon_is_killed(tmp_path):
    env = runtime()
    daemon = subprocess.Popen(
        [sys.executable, "-m", "varde_toz.daemon.server", "--idle", "10"],
        env=env,
        cwd=ROOT,
    )
    path = Path(env["XDG_RUNTIME_DIR"]) / "varde-toz" / "hook.sock"
    try:
        wait_for_socket(path, daemon)
        daemon.terminate()
        daemon.wait(timeout=3)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "varde_toz.daemon.client",
                "hook",
                "post-tool-use",
                "--harness",
                "claude",
            ],
            input=payload(),
            stdout=subprocess.PIPE,
            env=env,
            cwd=ROOT,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0
    finally:
        if daemon.poll() is None:
            daemon.terminate()
            daemon.wait(timeout=3)


@pytest.mark.usefixtures("unix_socket_bind")
def test_daemon_serves_concurrent_clients_and_exits_idle(tmp_path):
    env = runtime()
    daemon = subprocess.Popen(
        [sys.executable, "-m", "varde_toz.daemon.server", "--idle", "0.5"],
        env=env,
        cwd=ROOT,
    )
    path = Path(env["XDG_RUNTIME_DIR"]) / "varde-toz" / "hook.sock"
    try:
        wait_for_socket(path, daemon)
        calls = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "varde_toz.daemon.client",
                    "hook",
                    "post-tool-use",
                    "--harness",
                    "claude",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                env=env,
                cwd=ROOT,
            )
            for _ in range(4)
        ]
        outputs = [
            proc.communicate(payload(f"client-{index}"), timeout=5)[0]
            for index, proc in enumerate(calls)
        ]
        assert all(proc.returncode == 0 for proc in calls)
        assert len(outputs) == 4
        assert daemon.wait(timeout=3) == 0
        assert not path.exists()
    finally:
        if daemon.poll() is None:
            daemon.terminate()
            daemon.wait(timeout=3)


@pytest.mark.usefixtures("unix_socket_bind")
def test_client_uses_the_default_runtime_dir_socket(monkeypatch):
    from varde_toz.daemon import paths

    with tempfile.TemporaryDirectory(prefix="tz-") as runtime:
        runtime_dir = Path(runtime)
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        monkeypatch.setenv("TMPDIR", runtime)
        path = paths.socket_path()
        assert path.parent == runtime_dir / "varde-toz"

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(path))
        listener.listen(1)
        accepted = []

        def accept_and_close():
            connection, _ = listener.accept()
            accepted.append(True)
            with connection:
                while connection.recv(4096):
                    pass
            listener.close()

        thread = threading.Thread(target=accept_and_close)
        thread.start()
        env = {k: v for k, v in os.environ.items() if k != "XDG_RUNTIME_DIR"}
        env.update(TMPDIR=runtime, PYTHONPATH=str(ROOT / "src"))
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "varde_toz.daemon.client",
                "hook",
                "post-tool-use",
                "--harness",
                "claude",
            ],
            input=payload(),
            stdout=subprocess.PIPE,
            env=env,
            cwd=ROOT,
            timeout=5,
            check=False,
        )
        thread.join(timeout=3)
        assert result.returncode == 0
        assert accepted == [True]
