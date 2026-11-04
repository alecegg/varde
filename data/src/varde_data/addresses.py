"""Factory for selecting an address repository backend."""

from pathlib import Path

from varde_data.backends.memory.addresses import MemoryAddresses
from varde_data.repos.addresses import AddressRepository


def open_addresses(working: Path, backend_name: str) -> AddressRepository:
    """Open the configured address repository."""
    if backend_name == "files":
        from varde_data.backends.files.addresses import open_addresses as open_files

        return open_files(working)
    if backend_name == "memory":
        return MemoryAddresses()
    raise ValueError(f"unknown addresses backend: {backend_name}")


__all__ = ["open_addresses"]
