import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(("scan_status", "expects_warning"), [(0, False), (1, True)])
def test_pre_push_scan_is_report_only(
    tmp_path: Path, scan_status: int, expects_warning: bool
) -> None:
    root = tmp_path / "repo"
    hooks = root / ".githooks"
    hooks.mkdir(parents=True)
    (root / "justfile").write_text("default:\n\t@true\n")
    shutil.copy(REPO / ".githooks" / "pre-push", hooks / "pre-push")
    shutil.copy(REPO / ".githooks" / "lib.sh", hooks / "lib.sh")
    shutil.copy(REPO / ".githooks" / "pyright-stage", hooks / "pyright-stage")
    subprocess.run(["git", "init", "-q", str(root)], check=True)  # noqa: S603, S607 - Test initializes a temporary repository using the host Git executable.

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "scan-calls"
    varde = bin_dir / "varde"
    varde.write_text(f"#!/bin/sh\necho \"$@\" >> '{calls}'\nexit {scan_status}\n")
    varde.chmod(0o755)
    (hooks / "pyright-stage").write_text("\n")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    result = subprocess.run(  # noqa: S603 - Test runs a controlled local hook command to verify scan behavior.
        [str(hooks / "pre-push")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert f"scan --report --no-build --repo-root {root}" in calls.read_text()
    assert ("scan report failed" in output) == expects_warning
