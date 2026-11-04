"""The `[serve]` table of `config.toml`."""

from __future__ import annotations

import ipaddress
import tomllib
from dataclasses import dataclass
from pathlib import Path

LOOPBACK = "127.0.0.1"


@dataclass(frozen=True)
class ServeConfig:
    bind: str = LOOPBACK
    port: int = 0
    allow_edit: bool = False
    hosts: tuple[str, ...] = ()
    idle_s: float = 30 * 60


def is_loopback(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def parse_serve_table(table: dict) -> ServeConfig:
    """Build a ServeConfig from a `[serve]` table; raise ValueError on bad types."""
    defaults = ServeConfig()
    bind = table.get("bind", defaults.bind)
    port = table.get("port", defaults.port)
    allow_edit = table.get("allow_edit", defaults.allow_edit)
    hosts = table.get("hosts", [])
    idle_s = table.get("idle_s", defaults.idle_s)
    if not isinstance(bind, str) or not bind:
        raise ValueError("[serve] bind must be a string")
    if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        raise ValueError("[serve] port must be 0-65535")
    if not isinstance(allow_edit, bool):
        raise ValueError("[serve] allow_edit must be true or false")  # noqa: TRY004
    if not isinstance(hosts, list) or not all(isinstance(h, str) for h in hosts):
        raise ValueError("[serve] hosts must be a list of strings")
    if not isinstance(idle_s, int | float) or idle_s <= 0:
        raise ValueError("[serve] idle_s must be positive")
    return ServeConfig(bind, port, allow_edit, tuple(hosts), float(idle_s))


def load_serve_config(config_dir: Path) -> ServeConfig:
    path = config_dir / "config.toml"
    if not path.exists():
        return ServeConfig()
    table = tomllib.loads(path.read_text(encoding="utf-8")).get("serve", {})
    return parse_serve_table(table)


def bind_refusal(config: ServeConfig, requested: str | None) -> str | None:
    """Return why a bind is refused, else None.

    A non-loopback address is accepted only when `[serve] bind` names it.
    """
    address = requested or config.bind
    if is_loopback(address) or address == config.bind:
        return None
    return f"refusing non-loopback bind {address}: set [serve] bind to allow it"
