"""Every static ES module parses: a missing brace once shipped past the matrix."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).parents[2] / "src/varde_learn/docs/pages/static"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("path", sorted(STATIC.glob("*.js")), ids=lambda p: p.name)
def test_module_parses(path: Path) -> None:
    result = subprocess.run(  # noqa: S603
        [NODE or "node", "--check", "--input-type=module"],
        input=path.read_text("utf-8"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
