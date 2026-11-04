"""Build and run the PEX without changing the user's installed tools."""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).resolve().parents[1] / "pex" / "build.py"
SPEC = importlib.util.spec_from_file_location("varde_pex_build", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="varde-pex-") as directory:
        artifact = BUILD.build(Path(directory))
        result = subprocess.run(  # noqa: S603 - Builds the PEX in a child process as the smoke test's purpose.
            [str(artifact), "--help"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "usage:" in result.stdout.lower(), result.stdout
        print("PEX build and --help smoke passed")


if __name__ == "__main__":
    main()
