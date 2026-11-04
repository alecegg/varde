from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


def _run(command: list[str], home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    config = home / "config"
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(config),
        XDG_DATA_HOME=str(home / "data"),
        XDG_CACHE_HOME=str(home / "cache"),
        XDG_STATE_HOME=str(home / "state"),
        VARDE_CONFIG_DIR=str(config),
        VARDE_AGENTS_OPENCODE_VERSION="1",
    )
    result = subprocess.run(  # noqa: S603 - Runs the installed CLI to verify cross-install setup behavior.
        command, env=env, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_setup_sync_installs_preserves_and_dry_runs_skills(tmp_path: Path) -> None:
    home = tmp_path / "home"
    launcher = [str(Path(sys.executable).with_name("varde"))]
    skills = home / "skills"
    args = [
        "setup",
        "sync",
        "--harnesses",
        "none",
        "--skills-dir",
        str(skills),
        "--agents-dir",
        str(home / "agents"),
    ]
    _run([*launcher, *args], home)
    installed = skills / "varde-code/SKILL.md"
    assert installed.is_file()

    installed.write_text(installed.read_text() + "\nUser edit.\n")
    (installed.parent / ".varde-managed-skill").unlink()
    second = _run([*launcher, *args, "--json"], home)
    report_line = next(
        line for line in reversed(second.stdout.splitlines()) if line.startswith("{")
    )
    report = json.loads(report_line)
    assert report["ok"] is True
    assert "User edit." in installed.read_text()

    dry_home = tmp_path / "dry-home"
    dry_skills = dry_home / "skills"
    dry_args = [
        "setup",
        "sync",
        "--dry-run",
        "--harnesses",
        "none",
        "--skills-dir",
        str(dry_skills),
        "--agents-dir",
        str(dry_home / "agents"),
    ]
    dry = _run([*launcher, *dry_args], dry_home)
    assert "would install skill" in dry.stdout
    assert not dry_skills.exists()
