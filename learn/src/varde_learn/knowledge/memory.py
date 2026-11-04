"""Resolve project working and knowledge memory locations."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from varde_core import memory_dirs
from varde_core.memory_dirs import (
    canonical_or_lexical,
    repository_memory_root,
    resolve_memory_dir,
)
from varde_data.errors import Invalid
from varde_data.paths import resolve_learn_store

from varde_learn.knowledge.memory_config import config_path, load_config

WORKING_ENV = "VARDE_WORKING_DIR"
KNOWLEDGE_ENV = "VARDE_KNOWLEDGE_DIR"
MEMORY_ENV = "VARDE_MEMORY_DIR"
LEARN_ENV = "VARDE_LEARN_STORE"


class Source(StrEnum):
    ENV = "env"
    PROJECT = "project"
    DEFAULT = "default"
    BUILTIN = "builtin"


@dataclass(frozen=True)
class Resolved:
    path: Path
    source: Source


@dataclass(frozen=True)
class MemoryPaths:
    root: Path
    checkout_root: Path
    working: Resolved
    knowledge: Resolved
    memory: Resolved
    toz: Resolved | None
    learn: Resolved
    config: Path

    @classmethod
    def resolve(cls, root: str | Path) -> MemoryPaths:
        return cls.resolve_with(root, load_config().document)

    @classmethod
    def resolve_with(cls, root: str | Path, config: Any) -> MemoryPaths:
        checkout_root = canonical_or_lexical(Path(root))
        root = repository_memory_root(checkout_root)
        document = _document(config)
        project = memory_dirs.project_entry(document, root)
        defaults = memory_dirs.table(document.get("default"))

        def resolve_kind(kind: str) -> Resolved:
            path, source = resolve_memory_dir(root, kind, document)
            return Resolved(path, Source(source))

        toz_value = memory_dirs.path_value(project, "toz")
        toz_source = Source.PROJECT
        if toz_value is None:
            toz_value = memory_dirs.path_value(defaults, "toz")
            toz_source = Source.DEFAULT
        toz = (
            Resolved(memory_dirs.expand(root, toz_value), toz_source)
            if toz_value
            else None
        )

        learn_env = os.environ.get(LEARN_ENV)
        configured_learn = memory_dirs.path_value(defaults, "learn")
        try:
            learn_path = resolve_learn_store(config=document)
        except Invalid as error:
            raise ValueError(
                f"invalid learn store configuration at {config_path()}: {error}"
            ) from error
        learn_source = (
            Source.ENV
            if learn_env
            else Source.DEFAULT
            if configured_learn is not None
            else Source.BUILTIN
        )
        learn = Resolved(learn_path, learn_source)

        return cls(
            root,
            checkout_root,
            resolve_kind("working"),
            resolve_kind("knowledge"),
            resolve_kind("memory"),
            toz,
            learn,
            config_path(),
        )

    def get(self, kind: str) -> Resolved:
        if kind == "working":
            return self.working
        if kind == "knowledge":
            return self.knowledge
        if kind == "memory":
            return self.memory
        raise ValueError(f"unknown memory kind: {kind}")

    def write_roots(self) -> list[Path]:
        roots: list[Path] = []
        for iter_candidate in (
            self.checkout_root,
            self.root,
            self.working.path,
            self.knowledge.path,
            self.memory.path,
        ):
            candidate = canonical_or_lexical(iter_candidate)
            if any(candidate.is_relative_to(existing) for existing in roots):
                continue
            roots = [
                existing for existing in roots if not existing.is_relative_to(candidate)
            ]
            roots.append(candidate)
        return roots

    def contains(self, path: str | Path) -> bool:
        path = canonical_or_lexical(Path(path))
        return any(path.is_relative_to(root) for root in self.write_roots())


def find_root(start: str | Path) -> Path | None:
    start = canonical_or_lexical(Path(start))
    begin = start if start.is_dir() else start.parent
    try:
        config = load_config().document
    except OSError, ValueError:
        config = None
    if config is not None:
        for key in memory_dirs.table(_document(config).get("project")):
            root = Path(key)
            try:
                paths = MemoryPaths.resolve_with(root, config)
            except OSError, ValueError:
                continue
            dirs = (paths.working.path, paths.knowledge.path)
            if any(
                start.is_relative_to(canonical_or_lexical(path)) for path in dirs
            ) or start.is_relative_to(canonical_or_lexical(root)):
                return paths.root
    git_root = _git_top_level(begin)
    if git_root is not None:
        return repository_memory_root(git_root)
    return None


def _git_top_level(start: Path) -> Path | None:
    return _git_top_level_cached(canonical_or_lexical(start))


@lru_cache(maxsize=128)
# Per-process cache; repository changes do not invalidate it.
def _git_top_level_cached(start: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],  # noqa: S607 - Git is resolved from PATH.
            cwd=start,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return (
        canonical_or_lexical(Path(result.stdout.strip()))
        if result.returncode == 0
        else None
    )


def _document(config: Any) -> Any:
    return getattr(config, "document", config)


def _expand_global(value: str) -> Path:
    path = Path(value)
    if path.parts[:1] == ("~",):
        path = Path.home().joinpath(*path.parts[1:])
    return canonical_or_lexical(path if path.is_absolute() else Path.cwd() / path)
