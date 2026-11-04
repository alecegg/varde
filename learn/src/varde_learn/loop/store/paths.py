"""Compatibility adapters for shared learn store path checks."""

from pathlib import Path

from varde_data.errors import (
    GitStoreCheck,
    GitStorePath,
    Invalid,
    LearnStoreConfig,
    LearnStoreIo,
)
from varde_data.paths import (
    existing_directory,
    expand_leading_tilde,
    normalize_absolute,
    resolve_directory,
    validate_learn_store_path,
    work_tree_root,
)
from varde_data.paths import (
    reject_git_path as _reject_git_path,
)
from varde_data.paths import (
    reject_git_path_with as _reject_git_path_with,
)
from varde_data.paths import (
    resolve_learn_store as _resolve_learn_store,
)

from ..errors import StoreConfig, StoreGitCheck, StoreInsideGit, StoreIo


def resolve_store_dir(
    config_dir: Path | None = None, config: object | None = None
) -> Path:
    try:
        return _resolve_learn_store(config_dir=config_dir, config=config)
    except LearnStoreConfig as error:
        raise StoreConfig(error.path, error.message) from error
    except LearnStoreIo as error:
        raise StoreIo(error.operation, error.path, error.source) from error
    except Invalid as error:
        path = (config_dir or Path.cwd()) / "config.toml"
        raise StoreConfig(path, str(error)) from error
    except OSError as error:
        path = config_dir or Path.cwd()
        raise StoreIo("resolve store path", path, error) from error


def validate_global_path() -> None:
    validate_store_path(resolve_store_dir())


def validate_store_path(path: Path) -> None:
    try:
        validate_learn_store_path(path)
    except GitStorePath as error:
        raise StoreInsideGit(error.path, error.repo_root) from error
    except GitStoreCheck as error:
        raise StoreGitCheck(error.path, error.message) from error


def reject_git_path(path: Path) -> None:
    try:
        _reject_git_path(path)
    except GitStorePath as error:
        raise StoreInsideGit(error.path, error.repo_root) from error
    except GitStoreCheck as error:
        raise StoreGitCheck(error.path, error.message) from error


def reject_git_path_with(path: Path, will_be_ignored: bool = False) -> None:
    try:
        _reject_git_path_with(path, will_be_ignored)
    except GitStorePath as error:
        raise StoreInsideGit(error.path, error.repo_root) from error
    except GitStoreCheck as error:
        raise StoreGitCheck(error.path, error.message) from error


__all__ = [
    "existing_directory",
    "expand_leading_tilde",
    "normalize_absolute",
    "reject_git_path",
    "reject_git_path_with",
    "resolve_directory",
    "resolve_store_dir",
    "validate_global_path",
    "validate_store_path",
    "work_tree_root",
]
