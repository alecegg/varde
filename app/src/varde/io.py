"""App-provided capabilities shared with command modules."""

from varde_core.io import Io


def create_io() -> Io:
    """Build the default app capability set."""
    from .glue.contracts import io

    return io()
