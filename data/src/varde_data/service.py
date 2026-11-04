"""Cross-repository address workflows."""

from varde_data.repos.addresses import AddressRepository
from varde_data.repos.messages import MessageRepository


class AddressService:
    """Coordinate address changes that also update message-reader state."""

    def __init__(
        self, addresses: AddressRepository, messages: MessageRepository
    ) -> None:
        self.addresses = addresses
        self.messages = messages

    def add_alias(self, slot: str, alias: str | None = None) -> None:
        """Seed the slot's reader index before making its alias visible."""
        self.messages.register_reader(slot, from_start=True)
        self.addresses.add_alias(slot, alias)
