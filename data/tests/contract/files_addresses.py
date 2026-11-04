"""Factory for the files address repository contract backend."""

from pathlib import Path

from varde_data.backends.files.addresses import open_addresses
from varde_data.repos.addresses import AddressRepository


def factory(working: Path) -> AddressRepository:
    return open_addresses(working)
