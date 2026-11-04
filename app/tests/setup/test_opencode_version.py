import pytest
from varde.setup.opencode_version import MIN_V2, is_below_floor, parse_version


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("opencode v2.0.18", (2, 0, 18)),
        ("OpenCode 2.4.1", (2, 4, 1)),
        ("OpenCode 2.4", (2, 4, 0)),
        ("v2", (2, 0, 0)),
        ("OpenCode 2.x", (2, 0, 0)),
        ("1.4.2", (1, 4, 2)),
        ("no version", None),
    ],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize(
    ("version", "below"),
    [((1, 9, 99), False), ((2, 0, 17), True), ((2, 0, 18), False), ((2, 0, 32), False)],
)
def test_is_below_floor(version, below):
    assert MIN_V2 == (2, 0, 18)
    assert is_below_floor(version) is below
