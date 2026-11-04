"""Single-instance persistent hook server."""

from __future__ import annotations

import argparse
import fcntl
import io
import os
import socket
import sys
import threading
import time

from .paths import runtime_dir, socket_path


def _dispatch(data: bytes, harness: str, cwd: str) -> bytes:
    from varde_toz.hook import main

    previous_cwd = os.getcwd()
    os.chdir(cwd)
    old_stdin, old_stdout = sys.stdin, sys.stdout
    output = io.BytesIO()

    class Input:
        buffer = io.BytesIO(data)

    class Output:
        buffer = output

    try:
        sys.stdin, sys.stdout = Input(), Output()
        main(["post-tool-use", "--harness", harness])
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
        os.chdir(previous_cwd)
    return output.getvalue()


def _serve_one(connection: socket.socket, dispatch_lock: threading.Lock) -> None:
    with connection:
        data = bytearray()
        while True:
            part = connection.recv(65536)
            if not part:
                break
            data.extend(part)
            if len(data) > 8 * 1024 * 1024:
                return
        try:
            harness, separator, request = bytes(data).partition(b"\n")
            cwd, separator, payload = request.partition(b"\n")
            if not separator:
                return
            with dispatch_lock:
                reply = _dispatch(payload, harness.decode("ascii"), cwd.decode("utf-8"))
            connection.sendall(b"\x00" + reply)
        except Exception:
            return


def serve(idle_seconds: float = 30.0) -> int:
    directory = runtime_dir()
    lock_path = directory / "hook.lock"
    with lock_path.open("a+b") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        path = socket_path()
        try:
            path.unlink(missing_ok=True)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(path))
                os.chmod(path, 0o600)
                server.listen(16)
                server.settimeout(min(idle_seconds, 1.0))
                last_request = time.monotonic()
                dispatch_lock = threading.Lock()
                while time.monotonic() - last_request < idle_seconds:
                    try:
                        connection, _ = server.accept()
                    except TimeoutError:
                        continue
                    last_request = time.monotonic()
                    threading.Thread(
                        target=_serve_one, args=(connection, dispatch_lock), daemon=True
                    ).start()
        finally:
            path.unlink(missing_ok=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--idle", type=float, default=30.0)
    return serve(max(0.1, parser.parse_args(argv).idle))


if __name__ == "__main__":
    raise SystemExit(main())
