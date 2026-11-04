from pathlib import Path

import pytest
from varde.setup.autosave import run as autosave_run
from varde.setup.hooks_install import run as hooks_run
from varde.setup.old_store import SetupError, check_old_store


@pytest.mark.parametrize(
    ("legacy_path", "marker_store"),
    [
        ("home/.config/varde-code", "code"),
        ("xdg/tool-output-zone", "toz"),
    ],
)
@pytest.mark.parametrize("marker_present", [False, True])
def test_check_old_store_requires_migration_only_without_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    legacy_path: str,
    marker_store: str,
    marker_present: bool,
) -> None:
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    config = tmp_path / "config"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    (tmp_path / legacy_path).mkdir(parents=True)
    if marker_present:
        marker = config / marker_store / ".varde-migration-complete"
        marker.parent.mkdir(parents=True)
        marker.touch()

    if marker_present:
        check_old_store()
    else:
        refusal = "run varde-" + "rust's migrate first"
        with pytest.raises(SetupError, match=refusal) as error:
            check_old_store()
        assert error.value.exit_code == 1
        assert str(tmp_path / legacy_path) in str(error.value)


@pytest.mark.parametrize("marker_present", [False, True])
def test_check_old_store_allows_absent_legacy_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, marker_present: bool
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    if marker_present:
        for marker_store in ("code", "toz"):
            marker = tmp_path / "config" / marker_store / ".varde-migration-complete"
            marker.parent.mkdir(parents=True)
            marker.touch()

    check_old_store()


@pytest.mark.parametrize("command", ["hooks", "autosave"])
def test_setup_commands_reject_unmigrated_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, command: str
) -> None:
    home = tmp_path / "home"
    config = tmp_path / "config"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    (home / ".config/varde-code").mkdir(parents=True)

    if command == "hooks":
        status = hooks_run(["install", "--harness", "opencode"])
    else:
        status = autosave_run(["install", "--repo", str(tmp_path / "repo")], None)

    assert status == 1
    output = capsys.readouterr().err
    refusal = "run varde-" + "rust's migrate first"
    assert refusal in output
    assert str(home / ".config/varde-code") in output
