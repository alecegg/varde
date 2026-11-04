"""Small wake marker shared by inbox, binding, and relay state."""

from pathlib import Path

from varde_data.messages import touch_relay_wake


def touch(working: str | Path) -> None:
    touch_relay_wake(Path(working))
