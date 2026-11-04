"""Bind address rules for `varde learn docs serve --host`.

Loopback or Tailscale IPv4 only.
"""

from __future__ import annotations

import errno
import ipaddress

LOOPBACK = "127.0.0.1"
TAILSCALE_RANGE = ipaddress.ip_network("100.64.0.0/10")
LOOPBACK_NAMES = ("127.0.0.1", "localhost")


def classify_host(text: str) -> str:
    """Return canonical IPv4 text if `text` may be bound; else raise ValueError."""
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        raise ValueError(
            f"bad host {text!r}: use {LOOPBACK} or a Tailscale IPv4 "
            "address (100.64.0.0/10)"
        ) from None
    if address.version != 4:
        raise ValueError(
            f"host {text!r} refused: IPv6 is not supported; use an IPv4 address"
        )
    if str(address) == LOOPBACK or address in TAILSCALE_RANGE:
        return str(address)
    raise ValueError(
        f"host {text!r} refused: only {LOOPBACK} and Tailscale addresses "
        "(100.64.0.0/10) can be served"
    )


def is_loopback(host: str) -> bool:
    return host == LOOPBACK


def allowed_hosts(host: str, port: int) -> frozenset[str]:
    names = {f"{name}:{port}" for name in LOOPBACK_NAMES}
    return frozenset({f"{host}:{port}", *names})


def allowed_origins(host: str, port: int) -> frozenset[str]:
    return frozenset(f"http://{name}" for name in allowed_hosts(host, port))


def bind_error_message(error: OSError, host: str) -> str:
    """Explain a failed bind; an unassigned address means it is not on this machine."""
    if error.errno == errno.EADDRNOTAVAIL:
        return (
            f"cannot bind {host}: the address is not assigned to this machine "
            "(is Tailscale up? check `tailscale ip -4`)"
        )
    return str(error)
