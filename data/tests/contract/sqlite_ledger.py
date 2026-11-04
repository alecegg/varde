"""SQLite ledger factory for the contract suite: flips the domain, then opens."""

from pathlib import Path

from varde_data.backends.sqlite.learn_ledger import SqliteLedger
from varde_data.learn_store_mode import exclusive_store_lock, flip_domain_locked


def factory(root: Path) -> SqliteLedger:
    root.mkdir(parents=True, exist_ok=True)
    with exclusive_store_lock(root):
        flip_domain_locked(root, "ledger", "sqlite")
    return SqliteLedger(root)
