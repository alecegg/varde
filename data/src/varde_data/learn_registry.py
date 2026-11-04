"""Registry of learn domains: sqlite backend, handlers and file sources."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_data.learn_store_mode import Domain, backend_for


@dataclass(frozen=True)
class LearnDomain:
    """Lazy import targets and file sources for one learn domain."""

    name: Domain
    sqlite_module: str
    sqlite_attribute: str
    handlers_module: str
    source_files: tuple[str, ...]


LEARN_DOMAINS: dict[str, LearnDomain] = {
    "friction": LearnDomain(
        "friction",
        "varde_data.backends.sqlite.learn_friction",
        "SqliteLearnFriction",
        "varde_data.learn_handlers.friction",
        ("friction.jsonl", "learn.db"),
    ),
    "ledger": LearnDomain(
        "ledger",
        "varde_data.backends.sqlite.learn_ledger",
        "SqliteLedger",
        "varde_data.learn_handlers.ledger",
        ("analyzed.jsonl", "digests"),
    ),
    "calls": LearnDomain(
        "calls",
        "varde_data.backends.sqlite.learn_calls",
        "SqliteCalls",
        "varde_data.learn_handlers.calls",
        ("cli_calls.jsonl",),
    ),
}


class HandlersMissing(LookupError):
    """The domain has no migrate/verify/retire handlers yet."""


def domain(name: str) -> LearnDomain:
    try:
        return LEARN_DOMAINS[name]
    except KeyError:
        raise ValueError(f"unknown learn domain: {name}") from None


def load_sqlite_backend(name: str) -> Any:
    """Import the domain's sqlite backend class on demand."""
    spec = domain(name)
    module = importlib.import_module(spec.sqlite_module)
    return getattr(module, spec.sqlite_attribute)


def resolve_backend(root: Path, name: str, requested: str | None = None) -> str:
    """Pick the backend for a factory call.

    An explicit ``requested`` name (``memory`` for tests, or a name the caller
    forces) wins; otherwise the learn root's marker decides.
    """
    if requested is not None:
        return requested
    return backend_for(root, name)


def handler(name: str, operation: str) -> Callable[..., Any]:
    """Return one handler function (``rows``, ``migrate``, ``verify``, ``retire``)."""
    spec = domain(name)
    try:
        module = importlib.import_module(spec.handlers_module)
    except ModuleNotFoundError as exc:
        if not spec.handlers_module.startswith(exc.name or "\0"):
            raise
        raise HandlersMissing(f"{name} store handlers are not installed yet") from exc
    try:
        return getattr(module, operation)
    except AttributeError:
        raise HandlersMissing(f"{name} has no {operation} handler") from None


def source_files_present(root: Path, name: str) -> bool:
    return any((root / entry).exists() for entry in domain(name).source_files)
