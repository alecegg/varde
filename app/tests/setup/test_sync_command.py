import json
import tomllib

import pytest
from varde.setup.sync.command import run
from varde.setup.sync.report import MigrateEnv


def test_flag_paths_expand_home_and_resolve_relative_to_cwd(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "home").mkdir()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.chdir(work)

    assert (
        run(
            [
                "--skills-dir",
                "~/skills",
                "--agents-dir",
                "../agents",
                "--harnesses",
                "none",
                "--skills",
                "varde-build",
                "--dry-run",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert str(tmp_path / "home" / "skills") in output
    assert str(tmp_path / "agents") in output


def test_skills_all_clears_saved_selection(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text('[sync]\nskills = ["varde-build"]\n')
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config_dir))

    assert (
        run(
            [
                "--skills-dir",
                str(tmp_path / "skills"),
                "--agents-dir",
                str(tmp_path / "agents"),
                "--harnesses",
                "none",
                "--skills",
                "all",
                "--save",
            ]
        )
        == 0
    )

    assert "skills" not in tomllib.loads(config_file.read_text())["sync"]


def test_empty_skill_selection_is_rejected(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))

    assert (
        run(
            [
                "--skills-dir",
                str(tmp_path / "skills"),
                "--agents-dir",
                str(tmp_path / "agents"),
                "--harnesses",
                "none",
                "--skills",
                "varde-build,,varde-toz",
            ]
        )
        == 2
    )
    assert "must not be empty" in capsys.readouterr().err


def test_missing_targets_returns_usage_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    assert run(["--harnesses", "none"]) == 2
    assert "missing required targets" in capsys.readouterr().err


def test_help_does_not_need_targets(capsys):
    assert run(["--help"]) == 0
    output = capsys.readouterr().out
    assert "--dry-run" in output
    assert "--save" in output


@pytest.mark.parametrize("save,dry_run", [(False, False), (False, True), (True, True)])
def test_run_does_not_persist_flags_without_explicit_save(
    monkeypatch, tmp_path, capsys, save, dry_run
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    original = b"# user config\n[unrelated]\nvalue = 1\n"
    config_file.write_bytes(original)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    args = [
        "--skills-dir",
        str(tmp_path / "skills"),
        "--agents-dir",
        str(tmp_path / "agents"),
        "--link-mode",
        "copy",
        "--harnesses",
        "none",
    ]
    if save:
        args.append("--save")
    if dry_run:
        args.append("--dry-run")
    if save and dry_run:
        args.append("--json")

    assert run(args) == 0
    output = capsys.readouterr().out
    assert str(tmp_path / "skills") in output
    assert str(tmp_path / "agents") in output
    assert "copy" in output
    assert config_file.read_bytes() == original
    if save and dry_run:
        report = json.loads(output.splitlines()[-1])
        assert report["data"]["would"] == [
            {
                "path": str(config_dir / "toz"),
                "reason": "prediction: pin the resolved Toz store as the default",
                "command": (
                    f"varde setup paths set --default --toz {config_dir / 'toz'}"
                ),
            }
        ]


@pytest.mark.parametrize(
    "override",
    [
        ["--skills-dir", "skills"],
        ["--agents-dir", "agents"],
        ["--link-mode", "copy"],
        ["--skills", "varde-build"],
        ["--preset", "workflow"],
    ],
)
def test_each_override_is_run_local_without_save(
    monkeypatch, tmp_path, capsys, override
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    original = b"# user config\n[unrelated]\nvalue = 1\n"
    config_file.write_bytes(original)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config_dir))
    monkeypatch.chdir(tmp_path)

    args = [
        "--skills-dir",
        str(tmp_path / "skills"),
        "--agents-dir",
        str(tmp_path / "agents"),
        "--harnesses",
        "none",
        *override,
    ]
    assert run(args) == 0
    capsys.readouterr()
    assert config_file.read_bytes() == original


def test_save_flag_persists_settings_and_pins_toz(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    original = b"# user config\n[unrelated]\nvalue = 1\n"
    config_file.write_bytes(original)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert (
        run(
            [
                "--skills-dir",
                str(tmp_path / "skills"),
                "--agents-dir",
                str(tmp_path / "agents"),
                "--link-mode",
                "copy",
                "--skills",
                "varde-build",
                "--harnesses",
                "none",
                "--save",
            ]
        )
        == 0
    )
    saved = tomllib.loads(config_file.read_text())
    assert saved == {
        "unrelated": {"value": 1},
        "default": {"toz": str(config_dir / "toz")},
        "sync": {
            "skills_dir": str(tmp_path / "skills"),
            "agents_dir": str(tmp_path / "agents"),
            "link_mode": "copy",
            "skills": ["varde-build"],
        },
    }


def test_save_preserves_existing_toz_pin(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text('[default]\ntoz = "/existing/store"\n')
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config_dir))

    assert (
        run(
            [
                "--skills-dir",
                str(tmp_path / "skills"),
                "--agents-dir",
                str(tmp_path / "agents"),
                "--harnesses",
                "none",
                "--save",
            ]
        )
        == 0
    )
    saved = tomllib.loads(config_file.read_text())
    assert saved["default"]["toz"] == "/existing/store"
    assert "sync" in saved


def test_migrate_env_uses_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.delenv("VARDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert MigrateEnv.current().config_dir == tmp_path / "xdg" / "varde"


def test_malformed_saved_sync_config_returns_clean_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("[sync]\nskills_dir = 3\n")

    assert run(["--skills-dir", "skills", "--agents-dir", "agents"]) == 2
    assert (
        "varde setup sync: [sync].skills_dir must be a string"
        in capsys.readouterr().err
    )


def _preset_run(tmp_path, monkeypatch, extra=()):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    return run(
        [
            "--skills-dir",
            str(tmp_path / "skills"),
            "--agents-dir",
            str(tmp_path / "agents"),
            "--harnesses",
            "none",
            "--no-packs",
            *extra,
        ]
    )


def test_saved_renamed_presets_load_as_learn_notice_once(tmp_path, monkeypatch, capsys):
    (tmp_path / "home").mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text('[sync]\npresets = ["doc", "knowledge", "learn"]\n')

    assert _preset_run(tmp_path, monkeypatch) == 0
    first = capsys.readouterr().err
    assert "doc, knowledge" in first and "preset learn" in first
    assert tomllib.loads(config_file.read_text())["sync"]["presets"] == ["learn"]
    assert (tmp_path / "skills" / "varde-docs").exists()

    assert _preset_run(tmp_path, monkeypatch) == 0
    assert "preset learn" not in capsys.readouterr().err


@pytest.mark.parametrize("name", ["doc", "knowledge"])
def test_cli_preset_flag_for_renamed_preset_names_learn(
    tmp_path, monkeypatch, capsys, name
):
    (tmp_path / "home").mkdir()
    assert _preset_run(tmp_path, monkeypatch, ["--preset", name]) == 2
    assert "preset learn" in capsys.readouterr().err
