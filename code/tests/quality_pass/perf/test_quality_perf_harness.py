from __future__ import annotations

import importlib
import importlib.util
import itertools
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "code/scripts/code-index"


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_medium_fixture_is_seeded_formatted_and_requires_empty_directory(tmp_path):
    generator = load_script("make_medium_fixture")
    first = generator.generate(tmp_path / "first")
    second = generator.generate(tmp_path / "second")
    assert first == second
    assert first["file_count"] == 300
    assert len(first["tree_hash"]) == 64
    assert set(first["tree_hash"]) <= set("0123456789abcdef")
    assert len(list((tmp_path / "first/src/medium_py").glob("module_*.py"))) == 150
    assert len(list((tmp_path / "first/src/medium_ts").glob("module_*.ts"))) == 150
    assert (tmp_path / "first/README.md").is_file()
    assert (tmp_path / "first/src/main.py").is_file()
    sys.path.insert(0, str(tmp_path / "first/src"))
    try:
        module = importlib.import_module("medium_py.module_001")

        assert module.value == 1731
    finally:
        sys.path.remove(str(tmp_path / "first/src"))
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").touch()
    try:
        generator.generate(occupied)
    except ValueError as error:
        assert "must be empty" in str(error)
    else:
        raise AssertionError("non-empty fixture directory was accepted")


def test_medium_scenario_path_runs_with_noop_measurement(tmp_path, monkeypatch):
    harness = load_script("measure_index_ab")
    measure = load_script("measure_index")
    fixture_parent = tmp_path / "fixtures"
    harness.make_medium_fixture(fixture_parent)
    monkeypatch.setattr(measure, "FIXTURES", fixture_parent)
    calls = []
    monkeypatch.setattr(
        measure, "python_call", lambda action, repo, env: calls.append((action, repo))
    )
    writes = itertools.count()
    monkeypatch.setattr(measure, "ioreg_bytes", lambda: next(writes))
    monkeypatch.setattr(measure, "loadavg", lambda: [0.0, 0.0, 0.0])
    for scenario in ("cold", "no_change", "edit1"):
        rows = measure.execute(scenario, 1)
        assert len(rows) == 1
        assert rows[0]["wall_ms"] >= 0
    assert len(calls) == 5


def test_interleave_and_paired_bootstrap():
    harness = load_script("measure_index_ab")
    assert harness.interleaved_schedule(4) == [
        ("a", 0),
        ("b", 0),
        ("b", 1),
        ("a", 1),
        ("a", 2),
        ("b", 2),
        ("b", 3),
        ("a", 3),
    ]
    assert harness.paired_bootstrap([0.0, 0.0, 0.0]) == [0.0, 0.0]
    low, high = harness.paired_bootstrap([10.0, 10.0, 10.0])
    assert low == high == 10.0


def test_requires_out_and_rejects_any_nested_results_component(tmp_path):
    harness = load_script("measure_index_ab")
    repo = tmp_path / "repo"
    repo.mkdir()
    for output in (repo / "results/file.json", repo / "code/scripts/results/file.json"):
        try:
            harness.output_path(output, repo, repo)
        except ValueError as error:
            assert "results/" in str(error)
        else:
            raise AssertionError("repository results output was accepted")
    result = subprocess.run(  # noqa: S603 - Runs the performance harness with controlled arguments.
        [
            sys.executable,
            str(SCRIPTS / "measure_index_ab.py"),
            "--repo-a",
            str(repo),
            "--repo-b",
            str(repo),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "--out" in result.stderr


def test_dry_run_lock_branches_are_forced_by_environment(tmp_path):
    repo = ROOT
    lock = tmp_path / "lock"
    output = tmp_path / "ab.json"
    command = [
        sys.executable,
        str(SCRIPTS / "measure_index_ab.py"),
        "--repo-a",
        str(repo),
        "--repo-b",
        str(repo),
        "--fixture",
        "medium",
        "--out",
        str(output),
        "--dry-run",
    ]
    env = os.environ.copy()
    env["VARDE_LOCK_DIR"] = str(lock)
    refused = subprocess.run(  # noqa: S603 - Verifies the harness refuses a held lock.
        command, env=env, capture_output=True, text=True, check=False
    )
    assert refused.returncode != 0
    assert f"lock is not held: {lock}" in refused.stderr
    lock.mkdir()
    accepted = subprocess.run(  # noqa: S603 - Verifies the harness accepts a released lock.
        command, env=env, capture_output=True, text=True, check=False
    )
    assert accepted.returncode == 0
    assert "schedule: A1 B1" in accepted.stdout
