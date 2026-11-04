"""Shared message serialization for runner views."""

from typing import Any

from varde_data.records.messages import Message


def message_dict(message: Message) -> dict[str, Any]:
    return {
        "ts": message.ts,
        "from": message.from_,
        "to": message.to,
        "kind": message.kind,
        "text": message.text,
        **({"notes": message.notes} if message.notes is not None else {}),
        **({"id": message.id} if message.id is not None else {}),
    }


def recipient_matches_address(
    recipient: object, address: str, bindings: list[dict[str, Any]]
) -> bool:
    """Match a message recipient against an address and its registered aliases."""
    if recipient == address:
        return True
    for binding in bindings:
        slot = binding.get("slot")
        aliases = binding.get("aliases", [])
        if not isinstance(slot, str) or not isinstance(aliases, list):
            continue
        addresses = {slot, *(item for item in aliases if isinstance(item, str))}
        if address in addresses and recipient in addresses:
            return True
    return False
