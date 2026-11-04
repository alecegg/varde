"""Runner switch: read precedence and comment-preserving writers."""

import stat
from pathlib import Path

import pytest
from varde_data.config import (
    default_runner_enabled,
    runner_enabled,
    runner_switch_state,
    set_runner_enabled,
)
from varde_data.errors import Invalid


def _write(tmp_path: Path, text: str) -> None:
    (tmp_path / "config.toml").write_text(text, encoding="utf-8")


def test_default_off(tmp_path: Path) -> None:
    assert runner_enabled({}, tmp_path) is False
    assert runner_switch_state({}, tmp_path) == (False, "default")


def test_file_on(tmp_path: Path) -> None:
    _write(tmp_path, "[runner]\nenabled = true\n")
    assert runner_switch_state({}, tmp_path) == (True, "file")


@pytest.mark.parametrize(
    ("file_text", "env", "expected"),
    [
        ("[runner]\nenabled = false\n", "1", True),
        ("[runner]\nenabled = false\n", "TRUE", True),
        ("[runner]\nenabled = true\n", "0", False),
        ("[runner]\nenabled = true\n", "False", False),
    ],
)
def test_env_overrides_file(
    tmp_path: Path, file_text: str, env: str, expected: bool
) -> None:
    _write(tmp_path, file_text)
    assert runner_switch_state({"VARDE_RUNNER_ENABLED": env}, tmp_path) == (
        expected,
        "env",
    )


@pytest.mark.parametrize("env", ["yes", ""])
def test_other_env_falls_back_to_file(tmp_path: Path, env: str) -> None:
    _write(tmp_path, "[runner]\nenabled = true\n")
    assert runner_switch_state({"VARDE_RUNNER_ENABLED": env}, tmp_path) == (
        True,
        "file",
    )


@pytest.mark.parametrize(
    "text",
    [
        '[runner]\nenabled = "true"\n',
        "[runner]\nenabled = 1\n",
        "runner = 3\n",
        "[runner\n",
    ],
)
def test_odd_file_is_off(tmp_path: Path, text: str) -> None:
    _write(tmp_path, text)
    assert runner_enabled({}, tmp_path) is False


def test_set_keeps_comments_and_tables(tmp_path: Path) -> None:
    _write(tmp_path, "# top\n[other]\nkey = 1 # note\n")
    set_runner_enabled(True, tmp_path)
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert "# top" in text
    assert "key = 1 # note" in text
    assert runner_switch_state({}, tmp_path) == (True, "file")
    set_runner_enabled(False, tmp_path)
    assert runner_enabled({}, tmp_path) is False
    assert "# top" in (tmp_path / "config.toml").read_text(encoding="utf-8")


def test_set_creates_missing_dir(tmp_path: Path) -> None:
    set_runner_enabled(True, tmp_path / "sub")
    assert runner_enabled({}, tmp_path / "sub") is True


def test_default_writes_only_when_absent(tmp_path: Path) -> None:
    default_runner_enabled(tmp_path)
    assert runner_switch_state({}, tmp_path) == (True, "file")
    default_runner_enabled(tmp_path)
    assert runner_enabled({}, tmp_path) is True


def test_default_keeps_explicit_false(tmp_path: Path) -> None:
    _write(tmp_path, "[runner]\nenabled = false\n")
    default_runner_enabled(tmp_path)
    assert runner_enabled({}, tmp_path) is False


def test_non_utf8_reads_off_and_writers_raise_invalid(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_bytes(b"\xff\xfe[runner]\n")
    assert runner_enabled({}, tmp_path) is False
    with pytest.raises(Invalid):
        set_runner_enabled(True, tmp_path)
    with pytest.raises(Invalid):
        default_runner_enabled(tmp_path)


def test_malformed_existing_file_makes_writers_raise_invalid(tmp_path: Path) -> None:
    _write(tmp_path, "[runner\n")
    with pytest.raises(Invalid):
        set_runner_enabled(True, tmp_path)
    with pytest.raises(Invalid):
        default_runner_enabled(tmp_path)


def test_unwritable_target_raises_invalid_and_leaves_no_temp(tmp_path: Path) -> None:
    (tmp_path / "config.toml").mkdir()
    with pytest.raises(Invalid):
        set_runner_enabled(True, tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["config.toml"]


def test_set_keeps_other_keys_and_comments_in_runner_table(tmp_path: Path) -> None:
    _write(tmp_path, "[runner]\n# keep me\nname = 'x'\n")
    set_runner_enabled(True, tmp_path)
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "name = 'x'" in text
    assert runner_enabled({}, tmp_path) is True


def test_inline_table_is_read_and_updated(tmp_path: Path) -> None:
    _write(tmp_path, "runner = {enabled = true}\n")
    assert runner_enabled({}, tmp_path) is True
    set_runner_enabled(False, tmp_path)
    assert runner_enabled({}, tmp_path) is False


def test_padded_env_value_is_stripped(tmp_path: Path) -> None:
    assert runner_switch_state({"VARDE_RUNNER_ENABLED": " 1 "}, tmp_path) == (
        True,
        "env",
    )


def test_non_table_runner_is_replaced_on_write(tmp_path: Path) -> None:
    _write(tmp_path, "runner = 3\n")
    set_runner_enabled(True, tmp_path)
    assert runner_switch_state({}, tmp_path) == (True, "file")


def test_symlinked_config_updates_target_and_keeps_link(tmp_path: Path) -> None:
    real = tmp_path / "real.toml"
    real.write_text("# dotfile\n", encoding="utf-8")
    real.chmod(0o644)
    link = tmp_path / "config.toml"
    link.symlink_to(real)
    set_runner_enabled(True, tmp_path)
    assert link.is_symlink()
    assert "enabled = true" in real.read_text(encoding="utf-8")
    assert "# dotfile" in real.read_text(encoding="utf-8")
    assert stat.S_IMODE(real.stat().st_mode) == 0o644
