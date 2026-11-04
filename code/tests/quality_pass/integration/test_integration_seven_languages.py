"""A seven-language repository: cold, warm and no-cache passes agree bit for bit.

Each scenario runs in a fresh interpreter so ``PYTHONHASHSEED`` and the parsing
worker count differ between runs; the stored facts and measures must be
byte-identical across all of them, down to the record key order.
"""

from __future__ import annotations

import pytest
from integration_support import (
    EXPECTED_CALL_COVERAGE,
    EXPECTED_LOW_CONFIDENCE,
    SEVEN_LANGUAGE_FILES,
    SEVEN_LANGUAGE_REPO,
    build_index,
    measures_by_path,
    prepare_env,
    records_snapshot,
    run_pass_child,
    write_repo,
)
from varde_code.quality_pass.pass_ import run_quality_pass

pytestmark = pytest.mark.slow

FILE_COUNT = len(SEVEN_LANGUAGE_FILES)


def test_cold_warm_and_no_cache_facts_and_measures_are_bit_identical(
    tmp_path, monkeypatch
):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, SEVEN_LANGUAGE_REPO)

    cold = run_pass_child(root, "cold", workers=1, seed="0")
    # A warm pass has nothing pending, so its worker count cannot start a pool;
    # parallel parsing is covered by the cold worker-count test and the
    # no_cache pool runs below.
    warm = run_pass_child(root, "warm", workers=2, seed="1")
    no_cache = run_pass_child(root, "no_cache", workers=3, seed="2")
    second_no_cache = run_pass_child(root, "no_cache", workers=1, seed="97531")

    assert cold["facts_recomputed"] == list(SEVEN_LANGUAGE_FILES)
    assert cold["facts_reused"] == 0
    assert warm["facts_recomputed"] == []
    assert warm["facts_reused"] == FILE_COUNT
    assert warm["edges_recomputed"] == []
    assert warm["measures_recomputed"] == []
    assert warm["measures_reused"] == FILE_COUNT
    assert no_cache["facts_recomputed"] == list(SEVEN_LANGUAGE_FILES)
    assert no_cache["facts_reused"] == 0
    assert second_no_cache["facts_recomputed"] == list(SEVEN_LANGUAGE_FILES)

    snapshots = {
        records_snapshot(run) for run in (cold, warm, no_cache, second_no_cache)
    }
    assert len(snapshots) == 1
    assert len(cold["facts"]) == FILE_COUNT
    assert len(cold["measures"]) == FILE_COUNT


def test_cold_pass_is_bit_identical_across_worker_counts(tmp_path, monkeypatch):
    root_one = prepare_env(monkeypatch, tmp_path / "one")
    root_other = prepare_env(monkeypatch, tmp_path / "other")
    write_repo(root_one, SEVEN_LANGUAGE_REPO)
    write_repo(root_other, SEVEN_LANGUAGE_REPO)

    serial = run_pass_child(
        root_one, "cold", workers=1, seed="5", config_dir=tmp_path / "one" / "config"
    )
    parallel = run_pass_child(
        root_other,
        "cold",
        workers=4,
        seed="4096",
        config_dir=tmp_path / "other" / "config",
    )

    assert serial["facts_recomputed"] == list(SEVEN_LANGUAGE_FILES)
    assert parallel["facts_recomputed"] == list(SEVEN_LANGUAGE_FILES)
    assert records_snapshot(serial) == records_snapshot(parallel)


def test_cold_pass_resolves_cross_file_calls_for_expected_languages(
    tmp_path, monkeypatch
):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, SEVEN_LANGUAGE_REPO)
    build_index(root)

    run_quality_pass(root, workers=1)

    measures = measures_by_path(root)
    coverage = {
        path: measures[path]["call_coverage"] for path in EXPECTED_CALL_COVERAGE
    }
    assert coverage == EXPECTED_CALL_COVERAGE
    low = tuple(
        path
        for path, record in sorted(measures.items())
        if record["structure_confidence"] == "low"
    )
    assert low == EXPECTED_LOW_CONFIDENCE
