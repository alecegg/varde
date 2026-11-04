from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_test_env_routes_home_relative_paths_to_repo_scratch(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    script = repo / "core" / "scripts" / "test-env.sh"
    original_home = Path.home()
    result = subprocess.run(  # noqa: S603 - Test sources a controlled fixture script in a child shell.
        ["bash", "-c", 'source "$1"; env -0', "bash", str(script)],  # noqa: S607 - Test uses the system Bash to inspect its fixture.
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "HOME": str(original_home),
            "UV_CACHE_DIR": "",
            "VARDE_TREE_SITTER_SEED_DIR": str(tmp_path),
        },
    )
    values = dict(
        item.decode().split("=", 1) for item in result.stdout.split(b"\0") if item
    )
    scratch = repo / ".scratch" / "test-home"
    for name in (
        "HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "VARDE_CONFIG_DIR",
        "VARDE_TREE_SITTER_CACHE_DIR",
    ):
        assert Path(values[name]).is_relative_to(scratch)
    assert values["UV_CACHE_DIR"] == str(original_home / ".cache" / "uv")
