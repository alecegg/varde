from dataclasses import replace

import pytest
from varde_runner.config import ROLE_NAMES
from varde_runner.identity_profile import (
    ROLE_DESCRIPTIONS,
    ProfileError,
    defaults,
    parse,
    render,
    validate,
)


def fields(**overrides):
    return {
        "name": "Builder",
        "label": "Builder",
        "description": "",
        "role": "builder",
        **overrides,
    }


def test_defaults_include_each_role_and_manager():
    profiles = defaults(ROLE_NAMES)

    assert set(profiles) == {*ROLE_NAMES, "manager"}
    assert profiles["builder"].description == "Implements one task at a time."
    assert profiles["manager"].role == "manager"


def test_role_descriptions_cover_configured_roles():
    assert set(ROLE_NAMES) <= set(ROLE_DESCRIPTIONS)


def test_parse_render_round_trip():
    profile = defaults(ROLE_NAMES)["builder"]

    assert parse(render(profile)) == profile


def test_manager_parse_render_round_trip():
    profile = defaults(ROLE_NAMES)["manager"]

    assert parse(render(profile)) == profile


def test_parse_rejects_invalid_toml():
    with pytest.raises(ProfileError, match="invalid TOML"):
        parse("name = [")


def test_parse_rejects_unknown_file_stem():
    with pytest.raises(ProfileError, match="unknown identity"):
        parse(render(defaults(ROLE_NAMES)["builder"]), file_stem="custom")


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        (fields(name=""), "name"),
        (fields(name="x" * 41), "name"),
        (fields(label=""), "label"),
        (fields(name="  "), "name"),
        (fields(label="\t"), "label"),
        (fields(label="x" * 25), "label"),
        (fields(description="x" * 281), "description"),
        (fields(description="a\x7fb"), "description"),
        (fields(name="a\ud800"), "name"),
        (fields(label="a\x01b"), "label"),
        (fields(role="unknown"), "role"),
        ({"label": "Builder", "description": "", "role": "builder"}, "name"),
        (fields(name=3), "name"),
        (fields(label=3), "label"),
        (fields(description=3), "description"),
    ],
)
def test_validate_rejects_invalid_fields(fields, expected):
    assert expected in validate(fields)


def test_validate_rejects_unknown_file_stem():
    assert "role" in validate(fields(), file_stem="custom")


def test_validate_requires_role_to_match_file_stem():
    assert "role" in validate(fields(role="planner"), file_stem="builder")


def test_unicode_description_round_trip():
    profile = replace(defaults(ROLE_NAMES)["builder"], description="Café 🧭")

    assert parse(render(profile)) == profile
