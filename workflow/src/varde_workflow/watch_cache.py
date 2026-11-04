"""Persistent, per-watcher cache for plan watch frames."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

VERSION = 2


@dataclass
class CachedPlan:
    state: str
    bucket: int = 0
    blocked: set[str] = field(default_factory=set)
    idle_no_handback: bool = False


@dataclass
class WatchCache:
    version: int = VERSION
    plans: dict[str, CachedPlan] = field(default_factory=dict)


def cache_path_for_repo(working: Path, notes: Path | None, repo: Path) -> Path:
    identity = notes if notes is not None else repo
    canonical = _canonical(identity)
    digest = hashlib.sha1(os.fsencode(canonical)).hexdigest()[:12]  # noqa: S324 - Cache filename hashing needs no collision resistance or integrity.
    return working / ".cache" / f"plan-watch-{digest}.json"


def _canonical(path: Path) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError:
        parent = path.parent
        try:
            return parent.resolve(strict=True) / path.name
        except OSError:
            return path


def read_for_repo(working: Path, notes: Path | None, repo: Path) -> WatchCache | None:
    try:
        data = json.loads(
            cache_path_for_repo(working, notes, repo).read_text(encoding="utf-8")
        )
        if data.get("version") != VERSION or not isinstance(data.get("plans"), dict):
            return None
        plans = {
            key: CachedPlan(
                state=value["state"],
                bucket=value.get("bucket", 0),
                blocked=set(value.get("blocked", [])),
                idle_no_handback=value.get("idle_no_handback", False),
            )
            for key, value in data["plans"].items()
        }
        return WatchCache(VERSION, plans)
    except OSError, ValueError, TypeError, KeyError:
        return None


def write_if_changed_for_repo(
    working: Path, notes: Path | None, repo: Path, cache: WatchCache
) -> bool:
    path = cache_path_for_repo(working, notes, repo)
    data = {
        "version": cache.version,
        "plans": {
            key: {**asdict(value), "blocked": sorted(value.blocked)}
            for key, value in sorted(cache.plans.items())
        },
    }
    content = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()
    try:
        if path.read_bytes() == content:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return True
