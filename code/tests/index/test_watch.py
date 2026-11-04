from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import cast

from varde_code.index import watch
from watchdog.events import FileCreatedEvent


def test_foreground_watcher_initial_refresh_and_debounced_events(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    stopped = threading.Event()
    calls: list[Path] = []

    class Service:
        def ensure_fresh(self, repo: Path) -> None:
            calls.append(repo)
            if len(calls) == 2:
                stopped.set()

    class FakeObserver:
        handler: watch._Changed | None = None

        def schedule(self, handler, _path, recursive):
            assert recursive
            self.handler = handler

        def start(self):
            assert self.handler is not None
            self.handler.dispatch(FileCreatedEvent(str(root / "file.py")))
            time.sleep(0.01)
            assert self.handler is not None
            self.handler.dispatch(FileCreatedEvent(str(root / "file.py")))

        def stop(self):
            pass

        def join(self):
            pass

    monkeypatch.setattr(watch, "Observer", FakeObserver)
    watch.run_foreground(
        [root], cast("watch.IndexService", Service()), debounce=0.04, stop_event=stopped
    )

    assert calls == [root, root]


def test_foreground_watcher_ignores_git_events(tmp_path):
    from queue import Queue

    root = tmp_path / "repo"
    queue = Queue()
    handler = watch._Changed(root, queue)

    handler.on_created(FileCreatedEvent(str(root / ".git" / "config")))

    assert queue.empty()
