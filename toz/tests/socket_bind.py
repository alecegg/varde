import socket
import tempfile

import pytest


def socket_bind_blocked(family, socket_factory=None):
    if socket_factory is None:
        socket_factory = socket.socket
    with tempfile.TemporaryDirectory(prefix="varde-probe-") as directory:
        address = (
            f"{directory}/socket" if family == socket.AF_UNIX else ("127.0.0.1", 0)
        )
        try:
            with socket_factory(family, socket.SOCK_STREAM) as probe:
                probe.bind(address)
        except PermissionError:
            return True
        return False


def require_socket_bind(family):
    if socket_bind_blocked(family):
        pytest.skip(f"sandbox blocks {family} socket bind")
