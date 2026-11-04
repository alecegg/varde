from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]


def test_built_wheel_installs_and_runs_cli_commands(tmp_path: Path) -> None:
    output = tmp_path / "wheel"
    output.mkdir()
    env = os.environ.copy()
    subprocess.run(
        ["uv", "build", "--wheel", "--package", "varde", "--out-dir", str(output)],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--package",
            "varde-core",
            "--out-dir",
            str(output),
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--package",
            "varde-workflow",
            "--out-dir",
            str(output),
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(output.glob("*.whl"))
    assert {wheel.name.split("-")[0] for wheel in wheels} == {
        "varde",
        "varde_core",
        "varde_workflow",
    }
    venv = tmp_path / "venv"
    subprocess.run(
        ["uv", "venv", str(venv)], check=True, capture_output=True, text=True
    )
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--no-deps",
            "--python",
            str(python),
            *(str(wheel) for wheel in wheels),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    executable = venv / ("Scripts/varde.exe" if os.name == "nt" else "bin/varde")
    version = subprocess.run(
        [str(executable), "--version"], capture_output=True, text=True, check=False
    )
    assert version.returncode == 0
    assert version.stdout.startswith("varde ")
    help_result = subprocess.run(
        [str(executable), "setup", "sync", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_result.returncode == 0
    installed_scripts = list(
        (venv / "lib").glob(
            "python*/site-packages/varde_workflow/skills/varde-swarm/scripts/select-plans.py"
        )
    )
    assert installed_scripts
    result = subprocess.run(
        [str(python), str(installed_scripts[0]), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--working" in result.stdout
