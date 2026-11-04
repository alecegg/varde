"""Shared plan repositories keyed by their resolved working directory."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from varde_data.config import DataConfig, load_data_config
from varde_data.open import open_data
from varde_data.repos.plans import PlanRepositoryReader

_LOCK = threading.Lock()
_REPOSITORIES: dict[tuple[Path, str], PlanRepositoryReader] = {}


def plans_backend(environment: dict[str, str] | None = None) -> str:
    configured = load_data_config().backends.get("plans", "sqlite")
    backend = (environment or {}).get(
        "VARDE_PLANS_BACKEND",
        os.environ.get("VARDE_PLANS_BACKEND", configured),
    )
    if backend not in {"files", "sqlite"}:
        raise ValueError(f"unsupported runner plans backend: {backend}")
    return backend


def shared_plans_repository(
    working_dir: Path, environment: dict[str, str] | None = None
) -> PlanRepositoryReader:
    """Return the process-wide plan repository for this working directory."""
    resolved = working_dir.expanduser().resolve()
    backend = plans_backend(environment)
    with _LOCK:
        key = (resolved, backend)
        repository = _REPOSITORIES.get(key)
        if repository is not None:
            return repository
        config = load_data_config()
        config = DataConfig(
            backends={**config.backends, "plans": backend},
            learn_store=config.learn_store,
        )
        repository = open_data(resolved, config).plans
        _REPOSITORIES[key] = repository
        return repository


def clear_shared_plans_repositories() -> None:
    """Clear process-wide repository references between tests."""
    with _LOCK:
        _REPOSITORIES.clear()
