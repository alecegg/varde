"""Address families and client URLs for the configured bind."""

import socket

import pytest
from varde_serve.daemon.lifecycle import bound_listener
from varde_serve.daemon.security import allowed_hosts
from varde_serve.daemon.state import DaemonInfo


@pytest.mark.parametrize(
    ("bind", "host"),
    [
        ("127.0.0.1", "127.0.0.1"),
        ("0.0.0.0", "127.0.0.1"),  # noqa: S104 - connect-target mapping only
        ("::", "[::1]"),
        ("::1", "[::1]"),
        ("100.64.0.5", "100.64.0.5"),
    ],
)
def test_clients_connect_to_a_usable_host(bind: str, host: str) -> None:
    info = DaemonInfo(2, 8000, "now", "t", bind)
    assert info.host == host
    assert info.base_url == f"http://{host}:8000"


def test_ipv6_loopback_is_an_accepted_host() -> None:
    assert "[::1]:8000" in allowed_hosts(8000, ())


def test_ipv6_bind_uses_an_inet6_socket_and_a_failed_bind_is_an_oserror() -> None:
    try:
        listener = bound_listener("::1", 0)
    except OSError:
        pytest.skip("IPv6 loopback unavailable")
    with listener:
        assert listener.family == socket.AF_INET6
    with pytest.raises(OSError, match=r"."):
        bound_listener("203.0.113.1", 0)  # not a local address


def test_an_unbindable_address_exits_with_a_message_not_a_traceback(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    from varde_serve.daemon.config import ServeConfig
    from varde_serve.daemon.lifecycle import run_daemon

    config = ServeConfig(bind="203.0.113.1")
    assert run_daemon(tmp_path, "t", config=config) == 2
    assert "cannot bind 203.0.113.1" in capsys.readouterr().err
