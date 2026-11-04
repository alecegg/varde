from __future__ import annotations

import json

from varde_runner.web.settings import (
    APP_ICON_OPTIONS,
    DEFAULT_APP_ICON,
    read_settings,
    write_settings,
)


def test_settings_default_icon_and_legacy_icon_fall_back_to_current_default(tmp_path):
    path = tmp_path / "settings.json"
    assert read_settings(path) == {"app_icon": DEFAULT_APP_ICON}
    path.write_text(json.dumps({"app_icon": "26a"}))
    assert read_settings(path) == {"app_icon": DEFAULT_APP_ICON}


def test_corrupt_settings_use_empty_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("not json")
    assert read_settings(path) == {"app_icon": DEFAULT_APP_ICON}


def test_settings_allow_exactly_the_two_shipped_icons(tmp_path):
    path = tmp_path / "settings.json"
    assert [option["id"] for option in APP_ICON_OPTIONS] == ["slate-bronze", "dark"]
    assert write_settings(path, "dark") == {"app_icon": "dark"}
    assert read_settings(path) == {"app_icon": "dark"}


def test_settings_reject_unknown_icon(tmp_path):
    path = tmp_path / "settings.json"
    try:
        write_settings(path, "26c")
    except ValueError as error:
        assert str(error) == "invalid app_icon"
    else:
        raise AssertionError("invalid app icon was accepted")
