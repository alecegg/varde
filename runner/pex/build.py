"""Build a portable PEX for the runner from the locked workspace wheels."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def runner_version() -> str:
    metadata = tomllib.loads((ROOT / "runner/pyproject.toml").read_text())
    return metadata["project"]["version"]


def build(temp: Path) -> Path:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required to build the runner PEX")
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
    subprocess.run(  # noqa: S603 - Invokes the pinned workspace build tool.
        [uv, "build", "--all-packages", "--wheel", "--out-dir", str(wheelhouse)],
        cwd=ROOT,
        env=env,
        check=True,
    )
    output = temp / "varde-runner.pex"
    subprocess.run(  # noqa: S603 - Invokes pinned PEX tooling with fixed arguments.
        [
            uv,
            "tool",
            "run",
            "--from",
            "pex==2.103.4",
            "pex",
            f"varde-runner=={runner_version()}",
            "-f",
            str(wheelhouse),
            "-o",
            str(output),
            "--python-path",
            sys.executable,
            "--interpreter-constraint",
            "CPython>=3.14",
            "-m",
            "varde_runner:main",
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
