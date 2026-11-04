"""Shared data path helpers and learn store Git safety checks."""

from __future__ import annotations

import contextlib
import os
import stat
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from varde_core.paths import data_dir as core_data_dir
from varde_core.paths import varde_config_dir

from varde_data.errors import (
    GitStoreCheck,
    GitStorePath,
    LearnStoreConfig,
    LearnStoreIo,
)
from varde_data.learn_store_mode import DB_NAME, DOMAINS, read_learn_mode


def plan_comments_path(plan_path: Path) -> Path:
    """Return the append-only comment log path for a plan artifact."""
    plan_dir = (
        plan_path.parent if plan_path.name == "plan.md" else plan_path.parent.parent
    )
    return plan_dir / "comments.jsonl"


def data_dir() -> Path | None:
    """Return the platform data directory used by Varde."""
    return core_data_dir()


def resolve_learn_store(
    config_dir: Path | None = None, config: Any | None = None
) -> Path:
    """Resolve VARDE_LEARN_STORE, default.learn, or the config learn directory."""
    selected = os.environ.get("VARDE_LEARN_STORE")
    if selected:
        return _expand_and_resolve(Path(selected))

    root = config_dir if config_dir is not None else varde_config_dir()
    if config is None:
        config_path = root / "config.toml"
        try:
            text = config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            config = {}
        except OSError as error:
            raise LearnStoreIo("read global config", config_path, error) from error
        else:
            try:
                config = tomllib.loads(text)
            except tomllib.TOMLDecodeError as error:
                raise LearnStoreConfig(config_path, str(error)) from error

    default = config.get("default", {}) if isinstance(config, dict) else {}
    selected = default.get("learn") if isinstance(default, dict) else None
    if selected is not None and (not isinstance(selected, str) or not selected.strip()):
        raise LearnStoreConfig(
            root / "config.toml", "`default.learn` must be a non-empty path string"
        )
    target = Path(selected) if selected is not None else root / "learn"
    return _expand_and_resolve(target)


def _expand_and_resolve(path: Path) -> Path:
    path = expand_leading_tilde(path)
    if not path.is_absolute():
        try:
            path = Path.cwd() / path
        except OSError as error:
            raise LearnStoreIo(
                "resolve relative store path from current directory", path, error
            ) from error
    return resolve_directory(path)


def expand_leading_tilde(path: Path) -> Path:
    if not path.parts or path.parts[0] != "~":
        return path
    home = os.environ.get("HOME")
    if not home:
        raise LearnStoreConfig(path, "cannot expand `~` because HOME is unset")
    return Path(home).joinpath(*path.parts[1:])


def resolve_directory(path: Path, depth: int = 0) -> Path:
    if depth > 40:
        raise LearnStoreIo(
            "resolve symlinked store path",
            path,
            OSError("too many symlink levels"),
        )
    normalized = normalize_absolute(path)
    probe = normalized
    missing: list[str] = []
    while True:
        result = inspect_path_prefix(probe, missing, depth)
        if result is not None:
            return result
        if probe.parent == probe:
            raise LearnStoreIo(
                "resolve store path",
                normalized,
                FileNotFoundError("no existing parent directory"),
            )
        missing.append(probe.name)
        probe = probe.parent


def inspect_path_prefix(probe: Path, missing: list[str], depth: int) -> Path | None:
    try:
        metadata = probe.lstat()
    except OSError as error:
        if not isinstance(error, FileNotFoundError):
            raise LearnStoreIo("inspect store path", probe, error) from error
        return None
    if stat.S_ISLNK(metadata.st_mode):
        try:
            target = probe.readlink()
        except OSError as error:
            raise LearnStoreIo("read store path symlink", probe, error) from error
        destination = target if target.is_absolute() else probe.parent / target
        for component in reversed(missing):
            destination /= component
        return resolve_directory(destination, depth + 1)
    if stat.S_ISDIR(metadata.st_mode):
        try:
            resolved = probe.resolve(strict=True)
        except OSError as error:
            raise LearnStoreIo("canonicalize store path", probe, error) from error
        for component in reversed(missing):
            resolved /= component
        return resolved
    return None


def normalize_absolute(path: Path) -> Path:
    if not path.is_absolute():
        try:
            path = Path.cwd() / path
        except OSError as error:
            raise LearnStoreIo(
                "resolve store path from current directory", path, error
            ) from error
    normalized = Path(path.anchor)
    for component in path.parts[1:]:
        if component == ".":
            continue
        if component == "..":
            if normalized.exists():
                with contextlib.suppress(OSError):
                    normalized = normalized.resolve()
            normalized = normalized.parent
        else:
            normalized /= component
    return normalized


def reject_git_path(path: Path) -> None:
    reject_git_path_with(path, False)


def reject_git_path_with(path: Path, will_be_ignored: bool = False) -> None:
    existing_dir = existing_directory(path)
    result = git_command(
        [
            "-C",
            str(existing_dir),
            "rev-parse",
            "--is-inside-work-tree",
            "--is-inside-git-dir",
            "--is-bare-repository",
        ]
    )
    if result.returncode:
        if "not a git repository" in result.stderr:
            return
        raise GitStoreCheck(path, result.stderr)
    flags = result.stdout.splitlines()
    inside_work_tree, inside_git_dir, bare = (flag == "true" for flag in flags[:3])
    if not inside_work_tree and not inside_git_dir and not bare:
        return
    if bare or inside_git_dir:
        raise GitStorePath(path, existing_dir)
    if will_be_ignored:
        return
    root_result = git_command(["-C", str(existing_dir), "rev-parse", "--show-toplevel"])
    repo_root = (
        Path(root_result.stdout.strip())
        if root_result.returncode == 0
        else existing_dir
    )
    relative = path.relative_to(repo_root) if path.is_relative_to(repo_root) else path
    ignored = git_command(
        ["-C", str(repo_root), "check-ignore", "--quiet", str(relative)]
    )
    if ignored.returncode == 0:
        return
    if ignored.returncode == 1:
        raise GitStorePath(path, repo_root)
    raise GitStoreCheck(path, ignored.stderr.strip())


def work_tree_root(directory: Path) -> Path | None:
    result = git_command(["-C", str(directory), "rev-parse", "--show-toplevel"])
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def git_command(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_CEILING_DIRECTORIES",
    ):
        environment.pop(name, None)
    try:
        return subprocess.run(  # noqa: S603 - Runs a fixed Git probe with arguments supplied by the caller.
            ["git", *arguments],  # noqa: S607 - Git is resolved from PATH as the repository tool.
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
    except OSError as error:
        raise GitStoreCheck(
            Path(arguments[1]) if len(arguments) > 1 else Path("."), str(error)
        ) from error


def existing_directory(path: Path) -> Path:
    probe = path
    while True:
        try:
            if probe.is_dir():
                return probe.resolve(strict=True)
        except OSError:
            pass
        if probe.parent == probe:
            raise LearnStoreIo(
                "find an existing store parent",
                path,
                FileNotFoundError("no existing parent directory"),
            )
        probe = probe.parent


def validate_learn_store_path(path: Path | None = None) -> None:
    store_dir = resolve_directory(path or resolve_learn_store())
    database_path = resolve_directory(store_dir / "learn.db")
    bootstrapped = (
        not (store_dir / ".gitignore").exists() and database_path.parent == store_dir
    )
    reject_git_path_with(database_path, bootstrapped)
    if any(read_learn_mode(store_dir).mode(name) == "sqlite" for name in DOMAINS):
        sqlite_path = resolve_directory(store_dir / DB_NAME)
        reject_git_path_with(sqlite_path, bootstrapped)
