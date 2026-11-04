import socket

import pytest
from socket_bind import require_socket_bind


def test_require_socket_bind_skips_when_bind_is_forbidden(monkeypatch):
    def forbidden_bind(family, sock_type):
        raise PermissionError("sandbox")

    monkeypatch.setattr("socket_bind.socket.socket", forbidden_bind)

    with pytest.raises(pytest.skip.Exception, match="blocks"):
        require_socket_bind(socket.AF_UNIX)


def test_require_socket_bind_continues_when_bind_is_allowed(monkeypatch):
    monkeypatch.setattr("socket_bind.socket_bind_blocked", lambda family: False)

    require_socket_bind(socket.AF_UNIX)
