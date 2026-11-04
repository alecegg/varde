"""Lazy composition root for data domain repositories."""

import importlib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from varde_data.backends.sqlite.queue_schema import (
    SCHEMA_VERSION as QUEUE_SCHEMA_VERSION,
)
from varde_data.config import DataConfig
from varde_data.errors import Invalid
from varde_data.paths import resolve_learn_store


@dataclass(frozen=True)
class DomainRegistration:
    """Import target and supported schema version for a domain."""

    module: str
    attribute: str
    supported_version: int | None


DOMAIN_REGISTRY: dict[str, DomainRegistration] = {}
DOMAIN_REGISTRY["plans"] = DomainRegistration(
    "varde_data.plans", "open_plans", supported_version=None
)
DOMAIN_REGISTRY["messages"] = DomainRegistration(
    "varde_data.messages", "open_messages", supported_version=None
)
DOMAIN_REGISTRY["friction"] = DomainRegistration(
    "varde_data.friction", "open_friction", supported_version=None
)
DOMAIN_REGISTRY["addresses"] = DomainRegistration(
    "varde_data.addresses", "open_addresses", supported_version=None
)
DOMAIN_REGISTRY["chat"] = DomainRegistration(
    "varde_data.chat", "open_chat", supported_version=None
)
DOMAIN_REGISTRY["bot"] = DomainRegistration(
    "varde_data.bot", "open_bot", supported_version=None
)
DOMAIN_REGISTRY["queue"] = DomainRegistration(
    "varde_data.queue", "open_queue", supported_version=QUEUE_SCHEMA_VERSION
)
DOMAIN_REGISTRY["slots"] = DomainRegistration(
    "varde_data.queue", "open_slots", supported_version=None
)


class Data:
    """Lazy access to registered data domains."""

    def __init__(self, working_dir: Path, config: DataConfig) -> None:
        self.working_dir = working_dir
        self.config = config
        self._domains: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        registration = DOMAIN_REGISTRY.get(name)
        if registration is None:
            raise AttributeError(  # noqa: TRY003, RUF100
                f"{type(self).__name__!s} has no domain {name!r}"
            )
        if name not in self._domains:
            if registration.supported_version is not None:
                version_path = self.working_dir / ".cache" / "data" / f"{name}.version"
                check_schema_version(version_path, registration.supported_version)
            module: ModuleType = importlib.import_module(registration.module)
            factory = getattr(module, registration.attribute)
            default_backend = (
                "sqlite" if name in {"chat", "bot", "queue", "slots"} else "files"
            )
            fallback = (
                self.config.backends.get("chat", default_backend)
                if name == "bot"
                else default_backend
            )
            backend_name = self.config.backends.get(name, fallback)
            if name == "friction" and name not in self.config.backends:
                backend_name = None  # the learn store marker decides
            root = self.working_dir
            if name == "friction":
                root = self.config.learn_store or resolve_learn_store()
            self._domains[name] = factory(root, backend_name)
        return self._domains[name]


def open_data(working_dir: Path, config: DataConfig) -> Data:
    """Create a data handle; domain modules load only when accessed."""
    return Data(working_dir, config)


def check_schema_version(path: Path, supported: int) -> None:
    """Reject a store written by code with a newer schema."""
    try:
        raw = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise Invalid(f"cannot read store schema version {path}: {exc}") from exc  # noqa: TRY003, RUF100
    if not raw.isdecimal():
        raise Invalid(  # noqa: TRY003, RUF100
            f"invalid store schema version in {path}: {raw!r}"
        )
    stored = int(raw)
    if stored > supported:
        raise Invalid(  # noqa: TRY003, RUF100
            f"store schema version {stored} at {path} is newer than "
            f"supported version {supported}"
        )
