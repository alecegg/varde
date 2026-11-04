"""Exercise the documented uv tool install without touching user tool state."""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "app"


def run(command: list[str], *, env: dict[str, str], cwd: Path = ROOT) -> str:
    result = subprocess.run(  # noqa: S603 - Exercises the install command through a child process.
        command,
        check=True,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    return result.stdout


def main() -> None:
    uv = os.environ.get("UV", "uv")
    with tempfile.TemporaryDirectory(prefix="varde-uv-tool-") as temp_dir:
        temp = Path(temp_dir)
        env = os.environ.copy()
        env.update(
            {
                "UV_TOOL_DIR": str(temp / "tools"),
                "UV_TOOL_BIN_DIR": str(temp / "bin"),
                "UV_CACHE_DIR": str(temp / "cache"),
                "UV_NO_PROGRESS": "1",
            }
        )

        if platform.system() == "Linux":
            run(
                [
                    uv,
                    "pip",
                    "compile",
                    str(PACKAGE / "pyproject.toml"),
                    "--extra",
                    "runner",
                    "--python",
                    "3.14",
                    "--python-platform",
                    "aarch64-manylinux_2_34",
                    "--only-binary",
                    ":all:",
                    "--output-file",
                    str(temp / "linux-requirements.txt"),
                ],
                env=env,
            )
            print("Linux aarch64 binary dependency resolution passed")
            return

        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise RuntimeError("install smoke requires macOS arm64 or Linux")

        run(
            [
                uv,
                "tool",
                "install",
                "--force",
                "--with",
                "ast-grep-py==0.50.0",
                f"{PACKAGE}[runner]",
                "--python",
                "3.14",
            ],
            env=env,
        )
        varde = temp / "bin" / "varde"
        help_text = run([str(varde), "map", "--help"], env=env)
        assert help_text.strip(), "installed varde returned empty command help"

        tool_python = temp / "tools" / "varde" / "bin" / "python"
        versions = run(
            [
                str(tool_python),
                "-c",
                (
                    "from importlib.metadata import version; "
                    "print(version('ast-grep-py')); print(version('wasmtime'))"
                ),
            ],
            env=env,
        ).splitlines()
        assert versions == ["0.50.0", "49.0.0"], versions
        print("macOS arm64 uv tool install and command smoke passed")


if __name__ == "__main__":
    main()
