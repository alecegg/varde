"""Configuration for selecting data storage backends."""

import os
import shutil
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import tomlkit
from tomlkit.exceptions import TOMLKitError
from varde_core.paths import varde_config_dir

from varde_data.errors import Invalid

_BACKENDS = {"files", "memory", "sqlite", "mirror-files", "mirror-sqlite"}


@dataclass(frozen=True)
class DataConfig:
    """Configured backend names keyed by domain."""

    backends: Mapping[str, str] = field(default_factory=dict)
    learn_store: Path | None = None


def load_data_config(config_dir: Path | None = None) -> DataConfig:
    """Load ``data.toml`` and apply per-domain environment overrides."""
    root = config_dir if config_dir is not None else varde_config_dir()
    path = root / "data.toml"
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise Invalid(f"invalid data configuration {path}: {exc}") from exc  # noqa: TRY003, RUF100

    if not isinstance(raw, dict):
        raise Invalid(f"invalid data configuration in {path}: expected a table")  # noqa: TRY003, RUF100
    domains = raw.get("domains", {})
    if not isinstance(domains, dict) or any(
        not isinstance(domain, str) or not isinstance(backend, str)
        for domain, backend in domains.items()
    ):
        raise Invalid(f"invalid domains table in {path}")  # noqa: TRY003, RUF100

    backends = dict(domains)
    for domain, backend in tuple(backends.items()):
        backends[domain] = _validate_backend(domain, backend)

    for key, value in os.environ.items():
        prefix = "VARDE_DATA_"
        suffix = "_BACKEND"
        if key.startswith(prefix) and key.endswith(suffix):
            domain = key[len(prefix) : -len(suffix)].lower()
            if domain:
                backends[domain] = _validate_backend(domain, value)
    return DataConfig(backends=backends)


def _validate_backend(domain: str, backend: str) -> str:
    if backend not in _BACKENDS:
        raise Invalid(f"unknown backend {backend!r} for domain {domain!r}")  # noqa: TRY003, RUF100
    return backend


_ENV_SWITCH = "VARDE_RUNNER_ENABLED"
_ENV_VALUES = {"1": True, "true": True, "0": False, "false": False}


def runner_switch_state(
    env: Mapping[str, str] | None = None, config_dir: Path | None = None
) -> tuple[bool, str]:
    """Return the runner switch value and its source (env, file or default)."""
    environ = os.environ if env is None else env
    from_env = _ENV_VALUES.get(environ.get(_ENV_SWITCH, "").strip().lower())
    if from_env is not None:
        return from_env, "env"
    value = _read_runner_enabled(_config_path(config_dir))
    if value is None:
        return False, "default"
    return value, "file"


def runner_enabled(
    env: Mapping[str, str] | None = None, config_dir: Path | None = None
) -> bool:
    """Return whether the runner switch is on; any unreadable state is off."""
    return runner_switch_state(env, config_dir)[0]


def set_runner_enabled(value: bool, config_dir: Path | None = None) -> None:
    """Write ``[runner] enabled`` while keeping comments and other tables."""
    _write_runner_enabled(value, _config_path(config_dir))


def default_runner_enabled(config_dir: Path | None = None) -> None:
    """Write ``[runner] enabled = true`` only when the key is absent."""
    path = _config_path(config_dir)
    if _read_runner_enabled(path) is None:
        _write_runner_enabled(True, path)


def _config_path(config_dir: Path | None) -> Path:
    return (
        config_dir if config_dir is not None else varde_config_dir()
    ) / "config.toml"


def _read_runner_enabled(path: Path) -> bool | None:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    runner = raw.get("runner")
    if not isinstance(runner, dict):
        return None
    value = runner.get("enabled")
    return value if isinstance(value, bool) else None


def _write_runner_enabled(value: bool, path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        doc = tomlkit.parse(text)
        runner = doc.get("runner")
        if not isinstance(runner, dict):
            runner = tomlkit.table()
            doc["runner"] = runner
        runner["enabled"] = value
        _atomic_write(path, tomlkit.dumps(doc))
    except (OSError, ValueError, TOMLKitError) as exc:
        raise Invalid(f"cannot update {path}: {exc}") from exc  # noqa: TRY003, RUF100


def _atomic_write(path: Path, text: str) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".config.toml.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if target.exists():
            shutil.copymode(target, tmp)
        Path(tmp).replace(target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
