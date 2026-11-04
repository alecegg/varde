"""Build a portable PEX from the Python workspace's locked wheels."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build(temp: Path) -> Path:
    wheelhouse = temp / "wheelhouse"
    wheelhouse.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PEX_ROOT": str(temp / "pex-root"),
        "UV_CACHE_DIR": str(temp / "uv-cache"),
        "UV_NO_PROGRESS": "1",
        "UV_TOOL_DIR": str(temp / "uv-tools"),
        "UV_PYTHON_PREFERENCE": "only-system",
    }
    subprocess.run(
        ["uv", "build", "--all-packages", "--wheel", "--out-dir", str(wheelhouse)],
        cwd=ROOT,
        env=env,
        check=True,
    )
    output = temp / "varde.pex"
    subprocess.run(
        [
            "uv",
            "tool",
            "run",
            "--from",
            "pex==2.103.4",
            "pex",
            "varde==0.1.0",
            "-f",
            str(wheelhouse),
            "-o",
            str(output),
            "--only-binary",
            "tree-sitter-language-pack",
            "--python-path",
            sys.executable,
            "--interpreter-constraint",
            "CPython>=3.14",
            "-m",
            "varde.cli:main",
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    return output


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: build.py TEMP_DIR", file=sys.stderr)
        return 2
    build(Path(sys.argv[1]).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
