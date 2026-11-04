"""Read shipped sample records and optional per-user target overrides."""

from __future__ import annotations

import hashlib
import importlib.resources
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from varde_core.paths import varde_config_dir


@dataclass(frozen=True)
class Sample:
    id: str
    language: str
    task: str
    authored_by: str
    biases: tuple[str, ...]
    versions: Mapping[str, Path]
    target: Path
    user_target: bool


def load_sample(
    sample_id: str,
    *,
    package_root: str | Path | None = None,
    config_dir: str | Path | None = None,
) -> Sample:
    """Load one verified sample, applying its user target when present."""
    if not sample_id or Path(sample_id).name != sample_id:
        raise ValueError(f"invalid sample id: {sample_id!r}")
    root = (
        Path(package_root)
        if package_root is not None
        else Path(str(importlib.resources.files(__package__)))
    )
    directory = root / sample_id
    metadata_path = directory / "sample.toml"
    data = tomllib.loads(metadata_path.read_text(encoding="utf-8"))
    language = _required_string(data, "language")
    task = _required_string(data, "task")
    authored_by = _required_string(data, "authored_by")
    biases = data.get("biases")
    hashes = data.get("hashes")
    if not isinstance(biases, list) or not all(
        isinstance(item, str) for item in biases
    ):
        raise ValueError("sample biases must be a list of strings")
    if not isinstance(hashes, dict) or not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in hashes.items()
    ):
        raise ValueError("sample hashes must be a table of file digests")

    files = {
        path.name: path
        for path in directory.iterdir()
        if path.is_file() and path.name != "sample.toml"
    }
    if set(files) != set(hashes):
        raise ValueError("sample file hash manifest does not match files")
    for name, path in files.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != hashes[name]:
            raise ValueError(f"sample file hash mismatch: {name}")

    versions: dict[str, Path] = {}
    for path in files.values():
        if path.suffix and path.stem == "original":
            versions["original"] = path
        elif path.suffix and path.stem == "smoothed":
            versions["smoothed"] = path
        elif path.suffix and path.stem.startswith("judge-"):
            versions[path.stem] = path
    if "original" not in versions or "smoothed" not in versions:
        raise ValueError("sample requires original and smoothed source files")

    config = Path(config_dir) if config_dir is not None else varde_config_dir()
    user_target = (
        config
        / "quality"
        / "samples"
        / sample_id
        / f"target{versions['smoothed'].suffix}"
    )
    has_user_target = user_target.is_file()
    return Sample(
        sample_id,
        language,
        task,
        authored_by,
        tuple(biases),
        versions,
        user_target if has_user_target else versions["smoothed"],
        has_user_target,
    )


def component_diff(a: Mapping[str, int], b: Mapping[str, int]) -> dict[str, int]:
    """Return signed per-component debt changes from vector ``a`` to ``b``."""
    if set(a) != set(b):
        raise ValueError("component vectors must have identical component names")
    return {name: b[name] - a[name] for name in sorted(a)}


def _required_string(data: dict, name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"sample {name} must be a non-empty string")
    return value
