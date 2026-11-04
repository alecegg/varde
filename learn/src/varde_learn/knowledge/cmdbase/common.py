"""Common command path helpers."""

from pathlib import Path


def resolve_bundle(bundle: Path | str | None = None) -> Path:
    """Resolve an explicit bundle path, defaulting to the current directory."""
    return Path(bundle) if bundle is not None else Path.cwd()
