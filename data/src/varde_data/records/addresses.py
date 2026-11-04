"""Backend-neutral records for address, slot, and relay state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


@dataclass(frozen=True)
class AddressBinding:
    address: str
    session_id: str
    harness: str
    bound_at: datetime
    last_seen: datetime
    token_id: str
    extra: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ReaderContext:
    cwd: str = "."
    paseo_id: str | None = None
    agent_id: str | None = None
    runner_harness: str | None = None
    runner_endpoint: str | None = None
    # Launching agent's id; stored on the binding for runner launches.
    parent_id: str | None = None
    # Runner launch metadata is authoritative over hook process environment.
    runner_binding: bool = False
    env_address: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AddressSlot:
    slot: str
    aliases: tuple[str, ...] = ()
    current_address: str | None = None


@dataclass(frozen=True)
class AddressEvent:
    event: str
    at: datetime
    address: str | None = None
    session_id: str | None = None
    token_id: str | None = None
    session_key: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)


class ConfirmStatus(Enum):
    BEGUN = "begun"
    RESUME = "resume"
    DUPLICATE = "duplicate"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ConfirmStart:
    status: ConfirmStatus
    action: RelayAction | None = None
    result: str | None = None


@dataclass(frozen=True)
class RelayAction:
    action_id: str
    address: str
    message_ids: tuple[str, ...]
    token_id: str
    status: str
    created_at: datetime
    expires_at: datetime
    payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Retirement:
    addresses: frozenset[str] = frozenset()
    tokens: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RelaySnapshot:
    """Typed relay state; concluded addresses are owned by MessageRepository."""

    events: tuple[Mapping[str, object], ...] = ()
    leases: tuple[RelayAction, ...] = ()
    attempts: Mapping[str, tuple[Mapping[str, object], ...]] = field(
        default_factory=dict
    )
    mailman_started: Mapping[str, datetime] = field(default_factory=dict)
    retired: Retirement = field(default_factory=Retirement)
    concluded_addresses: frozenset[str] = frozenset()
    cycles: Mapping[str, int] = field(default_factory=dict)
    current_mailman: str | None = None
    mailman_instances: Mapping[str, str] = field(default_factory=dict)
    escalations: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
