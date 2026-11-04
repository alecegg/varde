"""Cold and warm results are identical across hash seeds and worker counts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pass_support import write_repo

pytestmark = pytest.mark.slow

CHILD = Path(__file__).with_name("pass_determinism_child.py")
REPO = {
    "pkg/__init__.py": "",
    "pkg/helper.py": "def compute(value):\n    return value + 1\n",
    "pkg/main.py": (
        "import pkg.helper\n\n\ndef entry():\n    return pkg.helper.compute(2)\n"
    ),
    "pkg/standalone.py": "def lonely():\n    return 5\n",
}
RUNS = [("0", "1"), ("1", "2"), ("12345", "3")]


def _run_all(tmp_path: Path, mode: str) -> list[str]:
    base = write_repo(tmp_path / f"base-{mode}", REPO)
    outputs = []
    for index, (seed, workers) in enumerate(RUNS):
        root = tmp_path / f"repo-{mode}-{index}"
        shutil.copytree(base, root)
        env = os.environ.copy()
        env.update(
            {
                "PYTHONHASHSEED": seed,
                "HOME": str(tmp_path / f"home-{mode}-{index}"),
                "XDG_CONFIG_HOME": str(tmp_path / f"xdg-{mode}-{index}"),
                "VARDE_CONFIG_DIR": str(tmp_path / f"config-{mode}-{index}"),
                "XDG_DATA_HOME": str(tmp_path / f"data-{mode}-{index}"),
            }
        )
        result = subprocess.run(  # noqa: S603 - Runs the deterministic pass fixture in a child process.
            [sys.executable, str(CHILD), str(root), workers, mode],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.append(result.stdout)
    return outputs


def test_results_do_not_depend_on_pythonhashseed_or_worker_count(tmp_path):
    outputs = _run_all(tmp_path, "noedit")

    assert len(set(outputs)) == 1
    payload = json.loads(outputs[0])
    assert payload["cold_recomputed"] == sorted(REPO)
    assert payload["warm_recomputed"] == []
    assert payload["warm_measures_recomputed"] == []
    assert payload["warm_reused"] == len(REPO)
    assert len(payload["facts"]) == len(REPO)
    assert len(payload["measures"]) == len(REPO)


def test_warm_after_edit_is_independent_of_seed_and_worker_count(tmp_path):
    outputs = _run_all(tmp_path, "edit")

    assert len(set(outputs)) == 1
    payload = json.loads(outputs[0])
    assert payload["warm_recomputed"] == ["pkg/standalone.py"]
    assert payload["warm_measures_recomputed"]
    assert len(payload["facts"]) == len(REPO)
    assert len(payload["measures"]) == len(REPO)
