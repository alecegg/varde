import pytest
from varde_data.cache import CachedData, UnstableDataError
from varde_data.version import Version


def test_write_during_load_retries_with_fresh_version() -> None:
    state = {"version": 0}
    loads = 0

    def load() -> int:
        nonlocal loads
        loads += 1
        if loads == 1:
            state["version"] = 1
        return state["version"]

    cached = CachedData(load, lambda: Version(state["version"]))

    assert cached.get() == 1
    assert loads == 2


def test_racy_timestamp_forces_reload_on_next_read() -> None:
    loads = 0

    def load() -> int:
        nonlocal loads
        loads += 1
        return loads

    version = Version("same", (1_000_000_000,))
    cached = CachedData(load, lambda: version, clock_ns=lambda: 1_000_000_000)

    assert cached.get() == 1
    assert cached.get() == 2


def test_io_error_preserves_last_good_value() -> None:
    state = {"fail": False}
    version_number = 0

    def load() -> str:
        if state["fail"]:
            raise OSError("unavailable")
        return "good"

    cached = CachedData(load, lambda: Version(version_number))
    assert cached.get() == "good"
    state["fail"] = True
    version_number += 1
    assert cached.get() == "good"


def test_first_io_error_is_raised() -> None:
    def fail() -> str:
        raise OSError("unavailable")

    cached = CachedData(fail, lambda: Version(0))
    with pytest.raises(OSError, match="unavailable"):
        cached.get()


def test_three_unstable_loads_raise() -> None:
    state = {"version": 0}

    def load() -> int:
        state["version"] += 1
        return state["version"]

    cached = CachedData(load, lambda: Version(state["version"]))
    with pytest.raises(UnstableDataError):
        cached.get()
