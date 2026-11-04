"""Scores are byte-identical cold versus warm, across hash seeds and worker counts."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from conftest import merged_facts, score_repo, write_files
from gate_snapshots import Snapshot
from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.build import build
from varde_code.quality_pass.pass_ import run_quality_pass
from varde_code.quality_score import score_scope
from varde_code.query import modes

_CHILD = textwrap.dedent(
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, sys.argv[1])
    from conftest import score_repo
    from gate_calibration import load_gate_test_calibration
    from gate_snapshots import SNAPSHOTS

    files = SNAPSHOTS[sys.argv[2]].files
    scope = score_repo(Path(sys.argv[3]), files, load_gate_test_calibration())
    sys.stdout.write(repr(scope))
    """
)


@pytest.fixture
def isolated_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """Repo root on a neutral path (a ``test_*`` dir makes files test paths)."""
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path_factory.mktemp("config")))
    monkeypatch.setattr(modes, "_INDEX_SERVICE", None)
    return tmp_path_factory.mktemp("det") / "repo"


@pytest.fixture
def neutral_tmp(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("seeds")


def _fingerprint(root: Path, calibration) -> str:
    """Serialize the scope score plus the merged facts that fed it."""
    scope = score_scope(merged_facts(root), calibration)
    return repr(scope) + repr(merged_facts(root))


def _child_score(snapshot: Snapshot, root: Path, config: Path, *, seed: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": seed, "VARDE_CONFIG_DIR": str(config)}
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-c",
            _CHILD,
            str(Path(__file__).parent),
            snapshot.language,
            str(root),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_cold_warm_and_uncached_scores_are_identical(
    snapshot: Snapshot, isolated_env: Path, gate_calibration
):
    root = isolated_env
    cold = score_repo(root, snapshot.files, gate_calibration)
    cold_print = _fingerprint(root, gate_calibration)

    warm_summary = run_quality_pass(root, workers=1)
    warm_print = _fingerprint(root, gate_calibration)
    run_quality_pass(root, no_cache=True, workers=1)
    uncached_print = _fingerprint(root, gate_calibration)

    assert not warm_summary.measures_recomputed
    assert not warm_summary.facts_recomputed
    assert repr(cold) == repr(score_scope(merged_facts(root), gate_calibration))
    assert warm_print == cold_print
    assert uncached_print == cold_print


def test_worker_count_does_not_change_scores(
    snapshot: Snapshot, isolated_env: Path, gate_calibration
):
    root = isolated_env
    write_files(root, snapshot.files)
    build(root, CodeExtractionProvider())
    prints = []
    for workers in (1, 4):
        run_quality_pass(root, no_cache=True, workers=workers)
        prints.append(_fingerprint(root, gate_calibration))
    assert prints[0] == prints[1]


def test_scores_are_identical_across_hash_seeds(
    snapshot: Snapshot, neutral_tmp: Path, gate_calibration
):
    outputs = []
    for seed in ("0", "1", "12345"):
        root = neutral_tmp / f"repo-{seed}"
        config = neutral_tmp / f"config-{seed}"
        outputs.append(_child_score(snapshot, root, config, seed=seed))
    assert outputs[0]
    assert outputs[0] == outputs[1] == outputs[2]
    local = score_repo(neutral_tmp / "local", snapshot.files, gate_calibration)
    assert repr(local) == outputs[0]
