"""Exporter validation for alt-good preference pairs."""

import pytest
from export_pairs import _alt_good_fields


@pytest.mark.parametrize(
    "pair",
    [
        {"left": "sensible.py", "right": "alt-pipeline.py"},
        {
            "left": "alt-pipeline.py",
            "right": "sensible.py",
            "left_role": "alt-good",
        },
        {
            "left": "sensible.py",
            "right": "regular.py",
            "right_role": "alt-good",
        },
    ],
)
def test_export_rejects_misassigned_alt_good_roles(pair: dict) -> None:
    with pytest.raises(ValueError, match="alt"):
        _alt_good_fields(pair)
