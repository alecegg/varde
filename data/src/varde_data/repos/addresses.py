"""Backend-neutral storage contract for address state."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Protocol

from varde_data.records.addresses import (
    AddressBinding,
    AddressEvent,
    AddressSlot,
    ConfirmStart,
    ReaderContext,
    RelayAction,
    RelaySnapshot,
    Retirement,
)
from varde_data.version import Version


class AddressRepository(Protocol):
    """Address storage operations; pure reads never acquire a write lock.

    Backend implementations serialize each documented write as one atomic
    operation. Cross-repository workflows belong to services, outside this API.
    Lock order is address -> relay -> events. Reads are lock-free snapshots;
    the slot lookup used during message claims is the lock-free-read exemption.
    """

    # Bindings and tokens
    def issue(
        self,
        address: str,
        *,
        ttl: timedelta = timedelta(hours=24),
        uses: int = 1,
        supersede: bool = False,
        now: datetime,
        issuer: str = "unknown",
    ) -> str:
        """WRITE: atomically supersede, purge, issue a token, and append its event."""
        ...

    def redeem(
        self,
        marker: str,
        session_id: str,
        harness: str,
        context: ReaderContext,
        *,
        now: datetime,
    ) -> bool:
        """WRITE atomically: consume one use, bind session and append its event."""
        ...

    def marker_error(self, marker: str, now: datetime) -> str:
        """Lock-free read describing why a marker cannot be redeemed."""
        ...

    def refresh_current(
        self,
        harness: str,
        session_id: str,
        context: ReaderContext,
        now: datetime,
    ) -> bool:
        """WRITE current binding metadata and last-seen time."""
        ...

    def resolve_reader(
        self,
        harness: str,
        session_id: str,
        marker: str | None,
        context: ReaderContext,
        now: datetime,
    ) -> str | None:
        """WRITE when redeeming a marker; otherwise resolve the session binding."""
        ...

    def unbind(self, selector: str, now: datetime) -> bool:
        """WRITE atomically removing current binding and invalidating its token."""
        ...

    def list_bindings(self) -> tuple[AddressBinding, ...]:
        """Lock-free read of full bindings, preserving unknown extra fields."""
        ...

    def live_addresses(self, now: datetime) -> frozenset[str]:
        """Lock-free read of addresses whose current binding is live."""
        ...

    def current_binding(self, address: str) -> AddressBinding | None:
        """Lock-free read of the current binding for an address."""
        ...

    def current_token(self, address: str) -> str | None:
        """Lock-free read of the current token id, even without a live binding."""
        ...

    def address_names(self) -> frozenset[str]:
        """Lock-free read of known address names represented in this store."""
        ...

    def token_issue_times(self) -> Mapping[str, tuple[datetime, ...]]:
        """Lock-free token issue times grouped by address."""
        ...

    def wake_of(self, address: str) -> Mapping[str, object] | None:
        """Lock-free read of wake metadata."""
        ...

    def mark_wake_gone(self, address: str, now: datetime) -> None:
        """WRITE wake-gone metadata."""
        ...

    def clear_wake_gone(self, address: str, now: datetime) -> None:
        """WRITE clearing wake-gone metadata."""
        ...

    def events(self) -> tuple[AddressEvent, ...]:
        """Lock-free read of complete append-only binding events."""
        ...

    def last_refusal(self, address: str) -> AddressEvent | None:
        """Lock-free read of the latest refusal event for an address."""
        ...

    # Slots
    def slots(self) -> tuple[AddressSlot, ...]:
        """Lock-free read of slot definitions."""
        ...

    def resolve_alias(self, name: str) -> str:
        """Lock-free read resolving a slot alias, leaving literal names intact."""
        ...

    def reader_addresses(self, name: str) -> frozenset[str]:
        """Lock-free read of the slot and all aliases served by its reader."""
        ...

    def add_alias(self, slot: str, alias: str | None = None) -> None:
        """WRITE atomically adding a slot alias; reader seeding is a service concern."""
        ...

    def remove_alias(self, alias: str) -> None:
        """WRITE atomically removing an alias from every slot."""
        ...

    # Relay state and actions
    def relay_snapshot(self) -> RelaySnapshot:
        """Lock-free typed read of relay state and retired address/token sets."""
        ...

    def record_event(
        self, event: str, *, now: datetime, data: Mapping[str, object] | None = None
    ) -> None:
        """WRITE relay event with waiting/returned dedupe and retention rules."""
        ...

    def record_events(self, events: Iterable[Mapping[str, object]]) -> None:
        """WRITE a batch of already-normalized relay events in one operation."""
        ...

    def record_send_liveness(
        self, message_id: str, recipient: str, now: datetime
    ) -> None:
        """WRITE send-liveness in the single-writer relay state operation."""
        ...

    def lease_actions(
        self,
        candidates: Iterable[Mapping[str, object]],
        token_id: str,
        now: datetime,
        *,
        lease_for: timedelta = timedelta(minutes=5),
        harness: str = "unknown",
    ) -> tuple[RelayAction, ...]:
        """WRITE: reserve eligible actions without duplicate message leases."""
        ...

    def begin_confirm(self, action_id: str, result: str, now: datetime) -> ConfirmStart:
        """WRITE confirmation state to confirming; safe to resume after a crash."""
        ...

    def finish_confirm(
        self,
        action_id: str,
        result: str,
        now: datetime,
        accepted_ids: Iterable[str],
        delivered: Iterable[tuple[str, str]],
    ) -> None:
        """WRITE final confirmation and shrink affected leases atomically."""
        ...

    def renew(
        self,
        action_id: str,
        now: datetime,
        *,
        lease_for: timedelta = timedelta(minutes=5),
    ) -> bool:
        """WRITE extending one active action lease."""
        ...

    def end(self, token_id: str, now: datetime, *, instance_id: str) -> None:
        """WRITE ending a mailman heartbeat."""
        ...

    def heartbeat(
        self,
        token_id: str,
        status: str,
        now: datetime,
        *,
        instance_id: str,
        expect_return_by: datetime | None = None,
    ) -> None:
        """WRITE heartbeat metadata and its lifecycle event."""
        ...

    def heartbeat_if_waiting(
        self,
        token_id: str,
        now: datetime,
        *,
        instance_id: str,
        expect_return_by: datetime | None = None,
    ) -> bool:
        """WRITE heartbeat only if this token is still the current waiting relay."""
        ...

    def return_mailman(
        self,
        token_id: str,
        now: datetime,
        expect_return_by: datetime,
        *,
        instance_id: str,
        completed: bool,
        reached_deadline: bool,
    ) -> bool:
        """WRITE return facts and increment cycle count when deadline was reached."""
        ...

    def mailman_alive(self, token_id: str, now: datetime) -> bool:
        """Lock-free read of mailman liveness from a consistent relay snapshot."""
        ...

    def action(self, action_id: str) -> RelayAction | None:
        """Lock-free read of one relay action."""
        ...

    def superseded(self, token_id: str) -> bool:
        """Lock-free read comparing token id with the current mailman token."""
        ...

    def reserve_escalation(self, key: str, outcome: str, now: datetime) -> bool:
        """WRITE compare-and-set reservation preventing duplicate escalation."""
        ...

    def reserve_escalations(
        self, keys: Iterable[str], outcome: str, now: datetime
    ) -> set[str]:
        """WRITE compare-and-set reservations for several escalations."""
        ...

    def reserve_suspect(self, key: str, now: datetime) -> bool:
        """WRITE compare-and-set reservation preventing duplicate suspects."""
        ...

    def retire(
        self, addresses: Iterable[str], tokens: Iterable[str], now: datetime
    ) -> None:
        """WRITE retirement timestamps for addresses and mailman tokens."""
        ...

    def unretire(self, addresses: Iterable[str]) -> None:
        """WRITE remove retirement timestamps for the selected addresses."""
        ...

    def retired(self) -> Retirement:
        """Lock-free read of retired addresses and token ids."""
        ...

    def retired_records(self) -> Mapping[str, str]:
        """Lock-free read of retirement timestamps keyed by address or mailman token."""
        ...

    def touch_wake(self) -> None:
        """WRITE wake/version signal without changing relay semantics."""
        ...

    def wake_token(self) -> Version:
        """Lock-free read token for wake-driven replanning."""
        ...

    def version(self) -> Version:
        """Lock-free version token covering every address-domain write."""
        ...
