"""Foreground filesystem watcher for keeping repository indexes fresh."""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from varde_code.index.slice import IndexService

LOGGER = logging.getLogger(__name__)
MAX_RECONCILE_DELAY = 30.0


class _Changed(FileSystemEventHandler):
    def __init__(self, repo: Path, events: queue.Queue[tuple[Path, float]]) -> None:
        self.repo = repo
        self.events = events

    def on_any_event(self, event: FileSystemEvent) -> None:
        source_path = event.src_path
        if isinstance(source_path, bytes):
            source_path = source_path.decode()
        path = Path(source_path)
        if ".git" in path.parts:
            return
        self.events.put((self.repo, time.monotonic()))


def run_foreground(
    repos: list[str | Path] | tuple[str | Path, ...],
    service: IndexService,
    *,
    debounce: float = 0.5,
    stop_event: threading.Event | None = None,
) -> None:
    """Watch repos until stopped, refreshing after quiet periods per repo.

    Each refresh uses the same advisory database lock as index builders.
    The initial refresh runs after observers are installed, so edits during
    startup are queued for a subsequent pass.
    """
    if debounce < 0:
        raise ValueError("debounce must be non-negative")
    roots = tuple(dict.fromkeys(Path(repo).resolve(strict=True) for repo in repos))
    if not roots:
        raise ValueError("at least one repository is required")
    stopped = stop_event or threading.Event()
    events: queue.Queue[tuple[Path, float]] = queue.Queue()
    observers: list[Any] = []
    for root in roots:
        observer = Observer()
        observer.schedule(_Changed(root, events), str(root), recursive=True)
        observer.start()
        observers.append(observer)

    try:
        for root in roots:
            _refresh(root, service)
        _reconcile_events(roots, service, events, stopped, debounce)
    finally:
        for observer in observers:
            observer.stop()
        for observer in observers:
            observer.join()


def _reconcile_events(
    roots: tuple[Path, ...],
    service: IndexService,
    events: queue.Queue[tuple[Path, float]],
    stopped: threading.Event,
    debounce: float,
) -> None:
    pending: dict[Path, tuple[float, float]] = {}
    last_periodic = time.monotonic()
    while not stopped.is_set():
        now = time.monotonic()
        deadlines = [
            min(last + debounce, first + MAX_RECONCILE_DELAY)
            for first, last in pending.values()
        ]
        timeout = max(0.01, min(deadlines, default=now + 30.0) - now)
        try:
            root, occurred = events.get(timeout=timeout)
            first, _last = pending.get(root, (occurred, occurred))
            pending[root] = (first, occurred)
        except queue.Empty:
            pass

        now = time.monotonic()
        due = [
            root
            for root, (first, last) in pending.items()
            if now - last >= debounce or now - first >= MAX_RECONCILE_DELAY
        ]
        for root in due:
            pending.pop(root, None)
            _refresh(root, service)
        if now - last_periodic >= MAX_RECONCILE_DELAY:
            for root in roots:
                _refresh(root, service)
            last_periodic = time.monotonic()


def _refresh(root: Path, service: IndexService) -> None:
    try:
        # IndexService's configured freshener owns the database lock; the
        # build and incremental writers both acquire it before modifying rows.
        service.ensure_fresh(root)
    except Exception:
        LOGGER.exception("index refresh failed for %s", root)
