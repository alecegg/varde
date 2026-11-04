"""A pass killed mid-work leaves a consistent store and the next pass recovers.

The child commits one fact row per file and one measure row per file; the parent
kills it at two different points (during the facts phase and during the measures
phase). A public-API rerun must reuse exactly the committed rows, finish the
rest, and end with the same facts and measures as a no-cache pass.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

import pytest
from integration_support import (
    PASS_CHILD,
    build_index,
    crash_repo_files,
    facts_by_path,
    measures_by_path,
    prepare_env,
    snapshot,
    write_repo,
)
from varde_code.quality_pass.pass_ import run_quality_pass

pytestmark = pytest.mark.slow

CRASH_FILES = 200
KILL_AFTER = 10


def _start_child(root, phase):
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "3"
    env["VARDE_TEST_KILL_PHASE"] = phase
    env["VARDE_TEST_KILL_AFTER"] = str(KILL_AFTER)
    return subprocess.Popen(  # noqa: S603 - Starts the test CLI to exercise crash recovery.
        [sys.executable, str(PASS_CHILD), str(root), "warm", "1"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_kill(process):
    _stdout, stderr = process.communicate(timeout=120)
    assert process.returncode == -signal.SIGKILL, stderr


def _recovered_snapshot(root):
    recovered = snapshot(root)
    run_quality_pass(root, workers=1, no_cache=True)
    assert snapshot(root) == recovered


def test_killed_during_facts_resumes_and_recomputes_the_rest(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    files = crash_repo_files(CRASH_FILES)
    write_repo(root, files)
    build_index(root)
    total = len(files)

    process = _start_child(root, "facts")
    _wait_for_kill(process)

    committed = facts_by_path(root)
    assert len(committed) == KILL_AFTER < total
    assert measures_by_path(root) == {}

    resumed = run_quality_pass(root, workers=1)

    assert resumed.facts_reused == len(committed)
    assert resumed.facts_recomputed == tuple(sorted(set(files) - set(committed)))
    assert resumed.edges_reused == 0
    assert resumed.edges_recomputed == tuple(sorted(files))
    assert resumed.measures_reused == 0
    assert resumed.measures_recomputed == tuple(sorted(files))

    _recovered_snapshot(root)


def test_killed_during_measures_resumes_and_reuses_facts_and_edges(
    tmp_path, monkeypatch
):
    root = prepare_env(monkeypatch, tmp_path)
    files = crash_repo_files(CRASH_FILES)
    write_repo(root, files)
    build_index(root)
    total = len(files)

    process = _start_child(root, "measures")
    _wait_for_kill(process)

    committed_facts = facts_by_path(root)
    committed_measures = measures_by_path(root)
    assert len(committed_facts) == total
    assert len(committed_measures) == KILL_AFTER < total

    resumed = run_quality_pass(root, workers=1)

    assert resumed.facts_reused == total
    assert resumed.facts_recomputed == ()
    assert resumed.edges_reused == total
    assert resumed.edges_recomputed == ()
    assert resumed.measures_reused == len(committed_measures)
    assert resumed.measures_recomputed == tuple(
        sorted(set(files) - set(committed_measures))
    )

    _recovered_snapshot(root)
