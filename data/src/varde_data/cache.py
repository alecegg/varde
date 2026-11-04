"""Version-checked cache for pure data reads."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from varde_data.version import Version

T = TypeVar("T")


class UnstableDataError(RuntimeError):
    """Raised when data changes during all three load attempts."""


class CachedData[T]:
    """Cache a read result while its source version remains unchanged."""

    def __init__(
        self,
        load: Callable[[], T],
        version: Callable[[], Version],
        *,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._load = load
        self._version = version
        self._clock_ns = clock_ns
        self._cached_version: Version | None = None
        self._value: T | None = None
        self._has_value = False
        self._loaded_at_ns = 0

    def get(self) -> T:
        current = self._version()
        cached_version = self._cached_version
        if (
            self._has_value
            and cached_version is not None
            and current == cached_version
            and not cached_version.is_racy_at(self._loaded_at_ns)
        ):
            return self._value  # type: ignore[return-value]

        for _ in range(3):
            before = self._version()
            try:
                value = self._load()
            except OSError:
                if self._has_value:
                    return self._value  # type: ignore[return-value]
                raise
            loaded_at = self._clock_ns()
            after = self._version()
            if before == after:
                self._cached_version = before
                self._value = value
                self._has_value = True
                self._loaded_at_ns = loaded_at
                return value

        if self._has_value:
            return self._value  # type: ignore[return-value]
        raise UnstableDataError
