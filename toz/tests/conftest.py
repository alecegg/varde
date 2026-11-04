import socket

import pytest
from socket_bind import require_socket_bind


@pytest.fixture
def unix_socket_bind():
    require_socket_bind(socket.AF_UNIX)


@pytest.fixture
def inet_socket_bind():
    require_socket_bind(socket.AF_INET)
