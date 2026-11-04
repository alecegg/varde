"""Small hook client; uses only the Python standard library socket/os/sys modules."""

import os
import socket
import sys


def _paths():
    base = (
        os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"  # noqa: S108 - Preserve the daemon's original shared socket directory fallback.
    )
    directory = os.path.join(base, "varde-toz")
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    return directory, os.path.join(directory, "hook.sock")


def _start_daemon():
    if os.fork() == 0:
        descriptor = os.open(os.devnull, os.O_RDWR)
        os.dup2(descriptor, 0)
        os.dup2(descriptor, 1)
        os.dup2(descriptor, 2)
        if descriptor > 2:
            os.close(descriptor)
        os.execv(  # noqa: S606 - Replace the forked child with this Python daemon process.
            sys.executable,
            [
                sys.executable,
                "-m",
                "varde_toz.daemon.server",
                "--idle",
                os.environ.get("VARDE_TOZ_DAEMON_IDLE", "30"),
            ],
        )


def _fallback(arguments, data):
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(write_fd)
        os.dup2(read_fd, 0)
        os.execv(  # noqa: S606 - Replace the forked child with this Python CLI process.
            sys.executable, [sys.executable, "-m", "varde_toz.cli", *arguments]
        )
    os.close(read_fd)
    offset = 0
    while offset < len(data):
        offset += os.write(write_fd, data[offset:])
    os.close(write_fd)
    _, status = os.waitpid(child, 0)
    return os.waitstatus_to_exitcode(status)


def main():
    _, path = _paths()
    arguments = sys.argv[1:]
    if not arguments or arguments[0] != "hook":
        arguments = ["hook", *arguments]
    harness = "claude"
    for index, argument in enumerate(arguments):
        if argument == "--harness" and index + 1 < len(arguments):
            harness = arguments[index + 1]
        elif argument.startswith("--harness="):
            harness = argument.partition("=")[2]
    payload = sys.stdin.buffer.read()
    data = harness.encode() + b"\n" + os.getcwd().encode() + b"\n" + payload
    connection: socket.socket | None = None
    try:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(1.0)
        connection.connect(path)
    except OSError:
        try:
            _start_daemon()
            for _ in range(2000):
                try:
                    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    connection.settimeout(1.0)
                    connection.connect(path)
                    break
                except OSError:
                    if connection is not None:
                        connection.close()
            else:
                return _fallback(arguments, payload)
        except OSError:
            return _fallback(arguments, payload)
    assert connection is not None  # noqa: S101 - The successful connect branch establishes this invariant before sending.
    try:
        connection.sendall(data)
        connection.shutdown(socket.SHUT_WR)
        response = bytearray()
        while True:
            part = connection.recv(65536)
            if not part:
                break
            response.extend(part)
        if response[:1] == b"\x00":
            sys.stdout.buffer.write(response[1:])
            return 0
        return _fallback(arguments, payload)
    except OSError:
        return _fallback(arguments, payload)
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
