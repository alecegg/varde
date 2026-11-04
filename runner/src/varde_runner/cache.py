"""Thread-safe TTL cache with per-key single-flight refreshes."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any


class SingleFlightCache:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._values: dict[str, tuple[float, Any, float, Exception | None]] = {}
        self._refreshing: set[str] = set()
        self._failing: set[str] = set()
        self._generations: dict[str, int] = {}
        self._loaders: dict[str, Callable[[], Any]] = {}

    def clear(self) -> None:
        with self._guard:
            for key in set(self._values) | self._refreshing | set(self._loaders):
                self._generations[key] = self._generations.get(key, 0) + 1
            self._values.clear()
            self._failing.clear()

    def invalidate(self, key: str, *, refresh: bool = True) -> None:
        with self._guard:
            self._generations[key] = self._generations.get(key, 0) + 1
            cached = self._values.get(key)
            if cached is not None:
                self._values[key] = (0.0, cached[1], 0.0, None)
                self._failing.discard(key)
            loader = self._loaders.get(key)
        if refresh and loader is not None and cached is not None:
            self._start_refresh(key, loader)

    def peek(self, key: str) -> Any | None:
        with self._guard:
            cached = self._values.get(key)
            return cached[1] if cached is not None and cached[3] is None else None

    def failing(self, key: str) -> bool:
        with self._guard:
            return key in self._failing

    def get_swr(self, key: str, ttl: float, loader: Callable[[], Any]) -> Any:
        with self._guard:
            self._loaders[key] = loader
        now = time.monotonic()
        cached = self._values.get(key)
        if cached is not None and cached[3] is None:
            if now - cached[0] < ttl:
                return cached[1]
            self._start_refresh(key, loader)
            return cached[1]
        return self.get(key, ttl, loader)

    def _start_refresh(self, key: str, loader: Callable[[], Any]) -> None:
        with self._guard:
            if key in self._refreshing:
                return
            self._refreshing.add(key)
            generation = self._generations.get(key, 0)

        def refresh() -> None:
            try:
                value = loader()
            except Exception:
                logging.getLogger(__name__).exception(
                    "Background cache refresh failed for %s", key
                )
                with self._guard:
                    if self._generations.get(key, 0) == generation:
                        self._failing.add(key)
                return
            else:
                with self._guard:
                    if self._generations.get(key, 0) == generation:
                        self._values[key] = (time.monotonic(), value, 0.0, None)
                        self._failing.discard(key)
            finally:
                with self._guard:
                    self._refreshing.discard(key)

        threading.Thread(target=refresh, daemon=True).start()

    def get(
        self,
        key: str,
        ttl: float,
        loader: Callable[[], Any],
        *,
        negative_ttl: float = 1.0,
    ) -> Any:
        now = time.monotonic()
        cached = self._values.get(key)
        if cached is not None and cached[3] is not None and now < cached[2]:
            if cached[1] is None:
                raise cached[3]
            return cached[1]
        if cached is not None and cached[3] is None and now - cached[0] < ttl:
            return cached[1]
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            now = time.monotonic()
            cached = self._values.get(key)
            if cached is not None and cached[3] is not None and now < cached[2]:
                if cached[1] is None:
                    raise cached[3]
                return cached[1]
            if cached is not None and cached[3] is None and now - cached[0] < ttl:
                return cached[1]
            with self._guard:
                generation = self._generations.get(key, 0)
            try:
                value = loader()
            except Exception as exc:
                with self._guard:
                    if self._generations.get(key, 0) == generation:
                        self._failing.add(key)
                        if cached is not None:
                            self._values[key] = (
                                cached[0],
                                cached[1],
                                now + negative_ttl,
                                exc,
                            )
                            return cached[1]
                        self._values[key] = (now, None, now + negative_ttl, exc)
                raise
            with self._guard:
                if self._generations.get(key, 0) == generation:
                    self._values[key] = (time.monotonic(), value, 0.0, None)
                    self._failing.discard(key)
            return value
