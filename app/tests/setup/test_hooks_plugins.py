from __future__ import annotations

from pathlib import Path

import pytest
from varde.setup.hooks_install import run


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    home.mkdir()
    bin_dir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    monkeypatch.setattr("sys.argv", [str(bin_dir / "varde")])
    return home, bin_dir


def path_for(home: Path, harness: str) -> Path:
    return home / (
        ".config/opencode/plugin/varde.ts"
        if harness == "opencode"
        else ".pi/agent/extensions/varde.ts"
    )


def test_plugins_install_and_remove(env, capsys):
    home, _ = env
    run(["install", "--harness", "opencode", "--harness", "pi"])
    output = capsys.readouterr().out
    for harness in ("opencode", "pi"):
        assert path_for(home, harness).exists()
    assert "user-prompt-submit unsupported" in output

    run(["remove", "--harness", "opencode", "--harness", "pi"])
    assert not path_for(home, "opencode").exists()
    assert not path_for(home, "pi").exists()


def test_stalled_opencode_probe_times_out(env, capsys):
    home, bin_dir = env
    probe = bin_dir / "opencode"
    # Absolute path: the fixture narrows PATH to bin_dir, so a bare `sleep`
    # would exit at once and the probe would never reach the timeout.
    probe.write_text("#!/bin/sh\n/bin/sleep 5\n")
    probe.chmod(0o755)

    assert run(["install", "--harness", "opencode"]) == 0

    assert "user-prompt-submit unsupported" in capsys.readouterr().out
    assert path_for(home, "opencode").exists()


def test_edited_plugin_is_kept_until_force(env, capsys):
    home, _ = env
    run(["install", "--harness", "pi"])
    target = path_for(home, "pi")
    edited = target.read_text() + "\n// user edit\n"
    target.write_text(edited)
    run(["remove", "--harness", "pi"])
    assert "blocked" in capsys.readouterr().out
    assert target.read_text() == edited
    run(["remove", "--harness", "pi", "--force"])
    assert not target.exists()
