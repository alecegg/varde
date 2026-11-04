"""Filesystem address repository implementation."""

from pathlib import Path

from varde_data.backends.files.addresses_bindings import FilesAddresses


def open_addresses(working: Path) -> FilesAddresses:
    """Open address bindings and slots in the established inbox store."""
    return FilesAddresses(working)


__all__ = ["FilesAddresses", "open_addresses"]
