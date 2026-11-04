"""Opt-in, non-overlapping duration spans for hook phase profiling."""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager

_active_spans: list[list[int | str]] = []


@contextmanager
def span(name: str) -> Iterator[None]:
    """Emit the exclusive duration, subtracting any nested measured spans."""
    started = time.perf_counter_ns()
    current: list[int | str] = [name, 0]
    _active_spans.append(current)
    try:
        yield
    finally:
        ended = time.perf_counter_ns()
        _active_spans.pop()
        elapsed = ended - started
        exclusive = elapsed - int(current[1])
        if _active_spans:
            _active_spans[-1][1] = int(_active_spans[-1][1]) + elapsed
        print(f"PHASE_TRACE|{name}|{exclusive}", file=sys.stderr)
