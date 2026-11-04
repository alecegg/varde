"""Pure recipient resolution for message sends."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from difflib import get_close_matches

from varde_data.records.addresses import AddressBinding, AddressSlot
from varde_data.roles import ROLES as _ROLES
from varde_data.roles import role_for_address


@dataclass(frozen=True)
class Resolved:
    address: str
    has_holder: bool
    is_role: bool


class RecipientError(ValueError):
    """A recipient could not be resolved uniquely."""

    def __init__(self, cause: str, name: str, candidates: Iterable[str] = ()) -> None:
        self.cause = cause
        self.name = name
        self.candidates = tuple(candidates)
        suffix = (
            f"; nearest addresses: {', '.join(self.candidates)}"
            if self.candidates
            else ""
        )
        super().__init__(f"{cause} recipient `{name}`{suffix}")


def _role_holders(
    role: str, slots: tuple[AddressSlot, ...], bindings: tuple[AddressBinding, ...]
) -> dict[str, str]:
    holders: dict[str, str] = {}
    for slot in slots:
        if role == "orchestrator" and slot.slot.startswith("orchestrator-"):
            holders.update(dict.fromkeys(slot.aliases, slot.slot))
        elif role != "orchestrator" and slot.slot.endswith(f"-{role}"):
            holders[slot.slot[: -(len(role) + 1)]] = slot.slot
    for binding in bindings:
        address = binding.address
        if role != "orchestrator" and address.endswith(f"-{role}"):
            holders[address[: -(len(role) + 1)]] = address
    return holders


def _resolve_role(  # noqa: PLR0911 - recipient cases return distinct outcomes.
    name: str,
    slots: tuple[AddressSlot, ...],
    bindings: tuple[AddressBinding, ...],
    live: frozenset[str],
    known: set[str],
) -> Resolved | None:
    if (
        name.startswith("orchestrator-")
        and name.removeprefix("orchestrator-").isdecimal()
    ):
        return Resolved(name, name in live, True)
    role, separator, qualifier = name.partition(":")
    if name == "main":
        role = "manager"
    if role not in _ROLES or (separator and not qualifier):
        return None
    if role == "manager":
        if qualifier:
            return None
        return Resolved("main", "main" in live, True)

    holders = _role_holders(role, slots, bindings)
    if qualifier:
        holder = holders.get(qualifier)
        if holder:
            return Resolved(holder, holder in live, True)
        if qualifier not in known:
            raise RecipientError(
                "unknown role qualifier", name, _nearest(qualifier, known)
            )
        mailbox = f"{qualifier}-{role}"
        return Resolved(mailbox, False, True)

    active = {key: value for key, value in holders.items() if value in live}
    if role in live:
        active["unqualified"] = role
    if len(active) > 1:
        raise RecipientError("ambiguous role", role, sorted(active))
    if active:
        return Resolved(next(iter(active.values())), True, True)
    if len(holders) > 1:
        raise RecipientError("ambiguous role", role, sorted(holders))
    if holders:
        return Resolved(next(iter(holders.values())), False, True)
    return Resolved(role, False, True)


def _nearest(name: str, candidates: set[str]) -> tuple[str, ...]:
    return tuple(get_close_matches(name, sorted(candidates), n=5, cutoff=0.35))


def resolve(
    name: str,
    slots: Iterable[AddressSlot],
    bindings: Iterable[AddressBinding],
    live: Iterable[str],
) -> Resolved:
    """Resolve a role, registered address, alias, or binding identity."""
    slot_rows = tuple(slots)
    binding_rows = tuple(bindings)
    live_addresses = frozenset(live)
    known = {"main", *live_addresses}
    candidates: dict[str, set[str]] = {}

    def add(value: str, address: str) -> None:
        known.add(value)
        candidates.setdefault(value, set()).add(address)

    for address in live_addresses:
        add(address, address)
    for slot in slot_rows:
        add(slot.slot, slot.slot)
        for alias in slot.aliases:
            add(alias, slot.slot)
    for binding in binding_rows:
        add(binding.address, binding.address)
        wake = binding.extra.get("wake_context")
        if not isinstance(wake, Mapping):
            continue
        for key in ("paseo_id", "paseo_agent_id", "agent_id"):
            identifier = wake.get(key)
            if isinstance(identifier, str) and identifier:
                add(identifier, binding.address)

    role_result = _resolve_role(name, slot_rows, binding_rows, live_addresses, known)
    if role_result is not None:
        return role_result

    exact = candidates.get(name, set())
    if len(exact) == 1:
        address = next(iter(exact))
        return Resolved(
            address,
            address in live_addresses,
            role_for_address(address) is not None,
        )
    if len(exact) > 1:
        raise RecipientError("ambiguous", name, _nearest(name, set(candidates)))

    if len(name) >= 8:
        prefix_matches = {
            address
            for binding in binding_rows
            for wake in (binding.extra.get("wake_context"),)
            if isinstance(wake, Mapping)
            for key in ("paseo_id", "paseo_agent_id", "agent_id")
            for identifier in (wake.get(key),)
            if isinstance(identifier, str) and identifier.startswith(name)
            for address in (binding.address,)
        }
        if len(prefix_matches) == 1:
            address = next(iter(prefix_matches))
            return Resolved(address, address in live_addresses, False)
        if len(prefix_matches) > 1:
            raise RecipientError("ambiguous", name, _nearest(name, set(candidates)))

    raise RecipientError("unknown", name, _nearest(name, set(candidates)))
