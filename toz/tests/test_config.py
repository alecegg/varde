from pathlib import Path

import pytest
from varde_toz.config import (
    ConfigError,
    config_dir,
    data_dir,
    env_os,
    load_config,
    resolve_config_dir,
    varde_config_dir,
    varde_toz_dir,
)


def test_config_env_precedence_and_migration_roots(tmp_path: Path) -> None:
    assert (
        env_os(
            "TOZ_CONFIG_DIR",
            {"VARDE_TOZ_CONFIG_DIR": "/canonical", "TOZ_CONFIG_DIR": "/alias"},
        )
        == "/canonical"
    )
    assert config_dir({"TOZ_CONFIG_DIR": "/explicit"}, tmp_path) == Path("/explicit")
    xdg = tmp_path / "xdg"
    legacy = xdg / "tool-output-zone"
    legacy.mkdir(parents=True)
    assert (
        resolve_config_dir(environ={"XDG_CONFIG_HOME": str(xdg)}, home=tmp_path)
        == legacy
    )
    (tmp_path / ".config" / "varde" / "toz" / ".varde-migration-complete").parent.mkdir(
        parents=True
    )
    marker_dir = tmp_path / ".config" / "varde" / "toz"
    (marker_dir / ".varde-migration-complete").touch()
    assert resolve_config_dir(environ={}, home=tmp_path) == marker_dir


def test_varde_path_helpers_and_data_dir(tmp_path: Path) -> None:
    assert varde_config_dir({"XDG_CONFIG_HOME": "/xdg"}, tmp_path) == Path("/xdg/varde")
    assert varde_config_dir({}, tmp_path) == tmp_path / ".config" / "varde"
    assert data_dir({"XDG_DATA_HOME": "/data"}, tmp_path, platform="linux") == Path(
        "/data"
    )
    assert (
        data_dir({"XDG_DATA_HOME": "relative"}, tmp_path, platform="linux")
        == tmp_path / ".local/share"
    )
    assert (
        data_dir({}, tmp_path, platform="darwin")
        == tmp_path / "Library/Application Support"
    )


def test_xdg_varde_aliases_and_precedence(tmp_path: Path) -> None:
    assert varde_config_dir(
        {"VARDE_XDG_CONFIG_HOME": "/varde-config"}, tmp_path
    ) == Path("/varde-config/varde")
    assert varde_config_dir(
        {"VARDE_XDG_CONFIG_HOME": "/preferred", "XDG_CONFIG_HOME": "/compat"}, tmp_path
    ) == Path("/preferred/varde")
    assert resolve_config_dir(
        environ={"VARDE_XDG_CONFIG_HOME": "/varde-config"}, home=tmp_path
    ) == Path("/varde-config/varde/toz")
    assert data_dir(
        {"VARDE_XDG_DATA_HOME": "/varde-data"}, tmp_path, platform="linux"
    ) == Path("/varde-data")
    assert data_dir(
        {"VARDE_XDG_DATA_HOME": "/preferred", "XDG_DATA_HOME": "/compat"},
        tmp_path,
        platform="linux",
    ) == Path("/preferred")


def test_varde_store_config_project_then_default_and_legacy_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "varde"
    root.mkdir()
    project = tmp_path / "work" / "project"
    project.mkdir(parents=True)
    (root / "config.toml").write_text(
        (
            f'[project."{project}".\ntoz = "~/stores/{{project}}"\n'
            '[default]\ntoz = "/default"\n'
        ).replace(f'[project."{project}".', f'[project."{project}"]'),
        encoding="utf-8",
    )
    assert (
        varde_toz_dir(project, environ={"VARDE_CONFIG_DIR": str(root)}, home=tmp_path)
        == tmp_path / "stores/project"
    )
    (root / "config.toml").unlink()
    (root / "paths.toml").write_text('[default]\ntoz = "/legacy"\n', encoding="utf-8")
    assert varde_toz_dir(
        project, environ={"VARDE_CONFIG_DIR": str(root)}, home=tmp_path
    ) == Path("/legacy")


def test_varde_project_config_precedence(tmp_path: Path) -> None:
    config_root = tmp_path / "varde"
    config_root.mkdir()
    project = tmp_path / "repo"
    project.mkdir()
    (config_root / "config.toml").write_text(
        (
            f'[project."{project}"]\ntoz = "/project-store"\n'
            '[default]\ntoz = "/default-store"\n'
        ),
        encoding="utf-8",
    )
    assert varde_toz_dir(
        project, environ={"VARDE_CONFIG_DIR": str(config_root)}, home=tmp_path
    ) == Path("/project-store")


def test_enabled_sandbox_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[sandbox]\nnetwork = true\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="sandbox.*not supported"):
        load_config(path)
    path.write_text("[sandbox]\nenabled = false\n", encoding="utf-8")
    sandbox = load_config(path)["sandbox"]
    assert isinstance(sandbox, dict)
    assert sandbox["enabled"] is False


@pytest.mark.parametrize("value", ["true", '"enabled"', "[]"])
def test_malformed_sandbox_fails_closed(tmp_path: Path, value: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f"sandbox = {value}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="sandbox.*table"):
        load_config(path)
