from dataclasses import FrozenInstanceError

import pytest
from varde_core.io import Io


def test_io_defaults_to_no_capabilities() -> None:
    io = Io()

    assert io.impact is None
    assert io.capture is None


def test_io_accepts_optional_capabilities() -> None:
    impact = object()
    capture = object()

    io = Io(impact=impact, capture=capture)

    assert io.impact is impact
    assert io.capture is capture


def test_io_is_frozen() -> None:
    io = Io()

    with pytest.raises(FrozenInstanceError):
        io.impact = object()  # type: ignore[misc]
