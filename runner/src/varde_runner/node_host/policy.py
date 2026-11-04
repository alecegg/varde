"""Crash policy for the Node host as a pure function."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RestartPolicy:
    max_restarts: int = 3
    window_s: float = 300.0
    delays_s: tuple[float, ...] = (1.0, 2.0, 4.0)


@dataclass(frozen=True, slots=True)
class Restart:
    delay_s: float


@dataclass(frozen=True, slots=True)
class GiveUp:
    deaths_in_window: int


def next_action(
    history: list[float], now: float, policy: RestartPolicy
) -> Restart | GiveUp:
    """Decide after a death; ``history`` includes the death at ``now``."""
    recent = sum(1 for died in history if now - died < policy.window_s)
    if recent > policy.max_restarts:
        return GiveUp(recent)
    index = min(max(recent, 1) - 1, len(policy.delays_s) - 1)
    return Restart(policy.delays_s[index] if policy.delays_s else 0.0)
