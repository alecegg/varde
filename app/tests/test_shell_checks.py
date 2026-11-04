import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_install_shared_files_shell_check() -> None:
    result = subprocess.run(  # noqa: S603 - Runs the shell checker as the test's integration target.
        ["bash", str(ROOT / "app/tests/install-shared-files.sh")],  # noqa: S607 - bash runs the repository's shell test script.
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
