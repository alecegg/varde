"""Typed errors raised by learn operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class LearnError(Exception):
    """Base error carrying the stable identifier used by CLI envelopes."""

    code: str


@dataclass
class NotImplemented(LearnError):
    feature: str
    code = "not_implemented"

    def __str__(self) -> str:
        return f"not implemented: {self.feature}"


@dataclass
class Usage(LearnError):
    message: str
    code = "usage_error"

    def __str__(self) -> str:
        return self.message


@dataclass
class StoreConfig(LearnError):
    path: Path
    message: str
    code = "store_config_error"

    def __str__(self) -> str:
        return (
            f"invalid global learn store configuration at {self.path}: {self.message}"
        )


@dataclass
class StoreInvalid(LearnError):
    message: str
    code = "store_invalid"

    def __str__(self) -> str:
        return f"invalid friction store operation: {self.message}"


@dataclass
class StoreItemNotFound(LearnError):
    identifier: str
    code = "store_item_not_found"

    def __str__(self) -> str:
        return f"friction item `{self.identifier}` was not found"


@dataclass
class StoreInsideGit(LearnError):
    path: Path
    repo_root: Path
    code = "store_inside_git"

    def __str__(self) -> str:
        return (
            f"refusing friction store at {self.path}: it is inside Git repository "
            f"{self.repo_root} and learn storage is not git-ignored there; git-ignore "
            "learn storage files in the repository, or set VARDE_LEARN_STORE / "
            "run `varde "
            "setup paths set --learn <dir>` to choose a store outside the repository"
        )


@dataclass
class StoreSchemaTooNew(LearnError):
    found: int
    supported: int
    code = "store_schema_too_new"

    def __str__(self) -> str:
        return (
            f"friction store schema version {self.found} is newer than supported "
            f"version {self.supported}; upgrade varde-learn"
        )


@dataclass
class StoreSchemaVersion(LearnError):
    value: str
    code = "store_schema_invalid"

    def __str__(self) -> str:
        return f"invalid friction store schema version `{self.value}`"


@dataclass
class StoreGitCheck(LearnError):
    path: Path
    message: str
    code = "store_git_check_failed"

    def __str__(self) -> str:
        return (
            f"could not verify whether friction store path {self.path} is inside Git: "
            f"{self.message}"
        )


@dataclass
class StoreIo(LearnError):
    operation: str
    path: Path
    source: OSError | UnicodeError
    code = "store_io_error"

    def __str__(self) -> str:
        return (
            f"could not {self.operation} friction store at {self.path}: {self.source}"
        )


@dataclass
class StoreDatabase(LearnError):
    path: Path
    source: Exception
    code = "store_database_error"

    def __str__(self) -> str:
        return f"could not initialize friction store at {self.path}: {self.source}"


@dataclass
class Diagnose(LearnError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message
