from pathlib import Path

import pytest
from varde_design.settings import (
    CONFIG_NAME,
    Settings,
    SettingsError,
    find_config,
    load_settings,
    parse_settings,
)


def test_empty_settings_give_neutral_defaults() -> None:
    settings = parse_settings({})
    assert settings == Settings()
    assert settings.min_target_px == 44
    assert settings.widths == (390, 768, 1440)
    assert settings.profile == "core"
    assert settings.spacing_scale is None


def test_values_override_defaults() -> None:
    settings = parse_settings(
        {
            "min_target_px": 24,
            "spacing_scale": [4, 8],
            "profile": "opinion",
            "ignore": ["S8"],
        }
    )
    assert settings.min_target_px == 24
    assert settings.spacing_scale == (4, 8)
    assert settings.profile == "opinion"
    assert settings.ignore == ("S8",)


def test_unknown_key_is_an_error() -> None:
    with pytest.raises(SettingsError, match="unknown setting: min_target"):
        parse_settings({"min_target": 24})


@pytest.mark.parametrize(
    "data",
    [
        {"min_target_px": "44"},
        {"min_target_px": 0},
        {"min_target_px": True},
        {"widths": []},
        {"widths": [390, "x"]},
        {"profile": "strict"},
        {"ignore": ["Z9"]},
        {"token_files": "a.css"},
        {"color_roles": {"ink": 3}},
    ],
)
def test_invalid_values_are_errors(data: dict[str, object]) -> None:
    with pytest.raises(SettingsError):
        parse_settings(data)


def test_loader_reads_toml_and_reports_bad_files(tmp_path: Path) -> None:
    good = tmp_path / CONFIG_NAME
    good.write_text(
        'max_motion_ms = 200\ntoken_files = ["a.css"]\n[color_roles]\nink = "--ink"\n'
    )
    settings = load_settings(good)
    assert settings.max_motion_ms == 200
    assert settings.token_files == ("a.css",)
    assert settings.color_roles == {"ink": "--ink"}
    assert find_config(tmp_path) == good
    bad = tmp_path / "bad.toml"
    bad.write_text("not = = toml")
    with pytest.raises(SettingsError, match="invalid TOML"):
        load_settings(bad)
    with pytest.raises(SettingsError, match="cannot read"):
        load_settings(tmp_path / "missing.toml")
    assert find_config(tmp_path / "nowhere") is None


def test_varde_configs_load() -> None:
    root = Path(__file__).resolve().parents[2]
    configs = ("varde-design.toml",)
    for config in (root / name for name in configs):
        assert load_settings(config).min_target_px == 44
