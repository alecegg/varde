"""Cells expected to fail until their widget task lands.

One line per family; a widget task deletes its own line. Family names are the
fixture families (`chrome` is the page chrome around blocks).
"""

PENDING: dict[str, str] = {}
