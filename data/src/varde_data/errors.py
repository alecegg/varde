"""Backend-independent errors exposed by the data layer."""


class DataError(Exception):
    """Base class for errors raised by the data layer."""


class NotFound(DataError):
    """The requested data does not exist."""


class Invalid(DataError):
    """The requested data is invalid."""


class WrongMode(DataError):
    """The requested operation is unavailable in the active store mode."""


class GitStorePath(Invalid):
    """A friction store path is unsafe inside a Git repository."""

    def __init__(self, path, repo_root) -> None:
        self.path = path
        self.repo_root = repo_root
        super().__init__(
            f"refusing friction store at {path}: it is inside Git repository "
            f"{repo_root} and learn storage is not git-ignored there"
        )


class GitStoreCheck(Invalid):
    """Git could not verify whether a friction store path is safe."""

    def __init__(self, path, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(
            f"could not verify whether friction store path {path} is inside Git: "
            f"{message}"
        )


class LearnStoreConfig(Invalid):
    """A learn store path setting cannot be used."""

    def __init__(self, path, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(message)


class LearnStoreIo(Invalid):
    """An I/O error occurred while resolving the learn store path."""

    def __init__(self, operation: str, path, source: OSError) -> None:
        self.operation = operation
        self.path = path
        self.source = source
        super().__init__(str(source))


class Conflict(DataError):
    """The requested change conflicts with current data."""


class Locked(DataError):
    """The requested data is locked by another operation."""
