"""Behavior tests for the quality-pass latency harness script."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "code/scripts/quality-pass/measure_quality.py"
SCENARIO_NAMES = (
    "cold_quality",
    "no_change_quality",
    "edit1_quality",
    "edit_hub_quality",
)


def load_script():
    spec = importlib.util.spec_from_file_location("measure_quality", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_cli(args, tmp_path: Path, lock: Path | None = None):
    env = os.environ.copy()
    env.update(
        {
            "VARDE_LOCK_DIR": str(lock if lock is not None else tmp_path / "absent"),
            "HOME": str(tmp_path / "home"),
            "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
            "VARDE_CONFIG_DIR": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        }
    )
    return subprocess.run(  # noqa: S603 - Runs the latency script under test with controlled arguments.
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def fake_sample(
    side: str,
    index_ms: float = 100.0,
    pass_ms: float | None = None,
    recomputed: int = 1,
) -> dict:
    work_ms = index_ms + (pass_ms or 0.0)
    startup_ms = 5.0
    summary = None
    if pass_ms is not None:
        summary = {
            "file_count": 3,
            "facts_recomputed": 1,
            "edges_recomputed": recomputed,
            "measures_recomputed": recomputed,
            "facts_reused": 2,
            "edges_reused": 1,
            "measures_reused": 2,
        }
    return {
        "wall_ms": work_ms + startup_ms,
        "work_ms": work_ms,
        "index_ms": index_ms,
        "pass_ms": pass_ms,
        "startup_ms": startup_ms,
        "device_write_bytes": 10,
        "paired_idle_write_bytes": 4,
        "load_average_1_5_15": [0.0, 0.0, 0.0],
        "pass_summary": summary,
    }


def test_dry_run_lists_every_scenario_without_lock_or_out(tmp_path):
    result = run_cli(["--dry-run"], tmp_path)
    assert result.returncode == 0
    assert "scenarios: " + " ".join(SCENARIO_NAMES) in result.stdout
    assert "schedule: A1 B1" in result.stdout
    assert "dry-run: PASS" in result.stdout


def test_out_is_required_and_repository_results_paths_are_refused(tmp_path):
    missing = run_cli(["--runs", "30"], tmp_path)
    assert missing.returncode != 0
    assert "--out" in missing.stderr

    repo = tmp_path / "repo"
    repo.mkdir()
    for relative in ("results/out.json", "code/results/out.json"):
        refused = run_cli(
            ["--dry-run", "--repo", str(repo), "--out", str(repo / relative)], tmp_path
        )
        assert refused.returncode != 0
        assert "results/" in refused.stderr


def test_measurement_refuses_without_the_lock(tmp_path):
    out = tmp_path / "out.json"
    refused = run_cli(["--runs", "30", "--out", str(out)], tmp_path)
    assert refused.returncode != 0
    assert "lock is not held" in refused.stderr
    assert not out.exists()


def test_dry_run_reports_the_lock_state(tmp_path):
    lock = tmp_path / "lock"
    lock.mkdir()
    held = run_cli(["--dry-run"], tmp_path, lock=lock)
    assert held.returncode == 0
    assert f"lock: held {lock}" in held.stdout
    absent = run_cli(["--dry-run"], tmp_path)
    assert "lock: not held" in absent.stdout


def test_lock_path_honours_the_lock_environment_and_default(tmp_path):
    module = load_script()
    lock = tmp_path / "held"
    assert module.lock_path({"VARDE_LOCK_DIR": str(lock)}) == lock
    assert module.lock_path({}) == module.load_harness().DEFAULT_LOCK


def test_schedule_interleaves_sides_after_discarded_warmup_pairs(tmp_path):
    module = load_script()
    calls = []

    def measure(scenario, side, target):
        calls.append((scenario, side))
        return fake_sample(side, 100.0, 0.0 if side == "b" else None)

    target = module.Target(
        "fake", "repo", "repo", tmp_path, hub="hub.py", leaf="leaf.py"
    )
    result = module.run_target(target, 2, measure=measure, warmup=1)

    assert calls[:6] == [
        ("cold_quality", "a"),
        ("cold_quality", "b"),
        ("cold_quality", "a"),
        ("cold_quality", "b"),
        ("cold_quality", "b"),
        ("cold_quality", "a"),
    ]
    assert len(calls) == len(SCENARIO_NAMES) * (1 + 2) * 2
    assert set(result["scenarios"]) == set(SCENARIO_NAMES)
    cold = result["scenarios"]["cold_quality"]
    assert cold["difference_ms"] == [0.0, 0.0]
    assert cold["bootstrap_95"] == [0.0, 0.0]
    assert cold["ratio_median"] == 0.0
    assert cold["a_work_ms_median"] == 100.0
    assert cold["b_pass_summary_median"]["measures_recomputed"] == 1
    assert cold["a"][0]["pass_summary"] is None
    assert cold["b"][0]["pass_summary"]["facts_recomputed"] == 1
    assert cold["a_net_write_bytes_median"] == 6
    assert cold["b_net_write_bytes_median"] == 6


def test_result_schema_and_ratio_proposals_use_the_pass_difference(tmp_path):
    module = load_script()

    def measure(scenario, side, target):
        return fake_sample(side, 100.0, 30.0 if side == "b" else None)

    target = module.Target("one", "repo", "repo", tmp_path)
    result = module.run_target(target, 3, measure=measure)
    out = tmp_path / "out.json"
    module.save_results(out, module.build_result("tiny", 3, [tmp_path], [result], 2))
    loaded = json.loads(out.read_text(encoding="utf-8"))

    assert loaded["machine_id"]
    assert len(loaded["load_average_1_5_15"]) == 3
    assert loaded["runs_per_scenario"] == 3
    assert loaded["warmup_pairs"] == 2
    assert loaded["scenarios"] == list(SCENARIO_NAMES)
    assert loaded["targets"][0]["size_class"] == "repo"
    row = loaded["targets"][0]["scenarios"]["cold_quality"]["b"][0]
    assert row["wall_ms"] == 135.0
    assert row["work_ms"] == 130.0
    assert row["index_ms"] == 100.0
    assert row["pass_ms"] == 30.0
    assert row["startup_ms"] == 5.0
    assert row["device_write_bytes"] == 10
    assert row["paired_idle_write_bytes"] == 4
    cold = loaded["targets"][0]["scenarios"]["cold_quality"]
    assert cold["difference_ms"] == [30.0, 30.0, 30.0]
    assert cold["bootstrap_95"] == pytest.approx([30.0, 30.0])
    assert cold["bootstrap_95_statistic"] == "mean of paired work_ms differences"
    assert cold["a_index_ms_median"] == 100.0
    assert cold["b_pass_ms_median"] == 30.0
    assert cold["a_startup_ms_median"] == 5.0
    assert cold["b_startup_ms_median"] == 5.0
    assert cold["ratio_median"] == pytest.approx(0.3)
    assert cold["ratio_bootstrap_95"] == pytest.approx([0.3, 0.3])
    assert "median of per-pair" in cold["ratio_bootstrap_95_statistic"]
    ratios = loaded["proposed_ratios"]
    assert ratios["by_target"]["one"]["cold_quality_k"] == pytest.approx(0.3)
    by_class = ratios["by_size_class"]["repo"]
    assert by_class["cold_quality_k"] == pytest.approx(0.3)
    assert by_class["no_change_quality_j"] == pytest.approx(0.3)
    assert by_class["edit1_quality_m"] == pytest.approx(0.3)
    assert by_class["edit_hub_quality_m"] == pytest.approx(0.3)


def test_size_class_comes_from_the_source_tree_file_count(tmp_path):
    module = load_script()
    root = tmp_path / "repo"
    for index in range(4):
        (root / "pkg").mkdir(parents=True, exist_ok=True)
        (root / "pkg" / f"mod_{index}.py").write_text("value = 1\n", encoding="utf-8")
    target = module.select_edit_files(module.Target("r", "repo", "", root))
    assert target.file_count == 4
    assert target.size_class == "tiny"

    assert module.size_class_for(11) == "medium"
    assert module.size_class_for(500) == "medium"
    assert module.size_class_for(501) == "large"


def test_unique_names_disambiguate_repositories_with_the_same_basename(tmp_path):
    module = load_script()
    names = module._unique_names(
        [tmp_path / "a" / "varde", tmp_path / "b" / "varde", tmp_path / "c" / "other"]
    )
    assert names == ["varde", "varde-2", "other"]


def test_resolve_targets_both_puts_the_tiny_and_medium_fixtures_side_by_side(tmp_path):
    module = load_script()
    targets = module.resolve_targets("both", [], tmp_path / "medium")
    assert [item.name for item in targets] == ["tiny", "medium"]
    assert [item.kind for item in targets] == ["tiny", "medium"]
    assert len(module._files(targets[0].path)) == 1
    assert len(module._files(targets[1].path)) == 302


def test_hub_prefers_imported_files_and_skips_test_paths(tmp_path):
    module = load_script()
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg/base_module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "pkg/mid_module.py").write_text("import base_module\n", encoding="utf-8")
    (root / "pkg/top_module.py").write_text(
        "from mid_module import x\n", encoding="utf-8"
    )
    (root / "pkg/spare_module.py").write_text("value = 1\n", encoding="utf-8")
    (root / "tests/test_base_module.py").write_text(
        "import base_module\n", encoding="utf-8"
    )

    target = module.select_edit_files(module.Target("r", "repo", "", root))
    assert target.file_count == 5
    assert target.hub == "pkg/base_module.py"
    assert target.leaf == "pkg/spare_module.py"
    assert target.hub_closure_size == 2
    assert target.leaf_closure_size == 0
    assert target.warnings == ()


def test_hub_edit_without_a_larger_closure_is_flagged(tmp_path):
    module = load_script()
    root = tmp_path / "repo"
    root.mkdir()
    (root / "solo.py").write_text("value = 1\n", encoding="utf-8")
    target = module.select_edit_files(module.Target("r", "repo", "", root))
    assert target.warnings == ("hub_closure_no_larger_than_leaf",)

    def measure(scenario, side, target):
        return fake_sample(side, 100.0, 30.0 if side == "b" else None, recomputed=1)

    result = module.run_target(target, 1, measure=measure)
    assert "hub_closure_no_larger_than_leaf" in result["warnings"]
    assert "hub_edit_recomputed=1 <= edit1_recomputed=1" in result["warnings"]
    improved = module.run_target(
        target,
        1,
        measure=lambda scenario, side, target: fake_sample(
            side,
            100.0,
            30.0 if side == "b" else None,
            recomputed=5 if scenario == "edit_hub_quality" else 1,
        ),
    )
    assert all("hub_edit_recomputed" not in item for item in improved["warnings"])
    assert (
        improved["scenarios"]["edit_hub_quality"]["b_pass_summary_median"][
            "measures_recomputed"
        ]
        == 5
    )


def test_hub_and_leaf_selection_then_edits_change_the_expected_files(tmp_path):
    module = load_script()
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg/base_module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "pkg/mid.py").write_text("import base_module\n", encoding="utf-8")
    (root / "pkg/top.py").write_text("from mid import x\n", encoding="utf-8")
    (root / "pkg/standalone.py").write_text("value = 1\n", encoding="utf-8")

    target = module.select_edit_files(module.Target("r", "repo", "", root))
    assert target.hub == "pkg/base_module.py"
    assert target.leaf == "pkg/standalone.py"

    module.apply_edit(root, target, "edit1_quality")
    leaf_text = (root / "pkg/standalone.py").read_text(encoding="utf-8")
    assert leaf_text.endswith("# one-file benchmark edit\n")

    before = (root / "pkg/base_module.py").read_text(encoding="utf-8")
    module.apply_edit(root, target, "edit_hub_quality")
    after = (root / "pkg/base_module.py").read_text(encoding="utf-8")
    assert after.startswith(before)
    assert "def qs_hub_probe()" in after
    assert module.edit_marker(Path("x.ts")) == "//"
    assert module.edit_marker(Path("x.py")) == "#"


def test_output_path_accepts_a_temporary_path_and_refuses_nested_results(tmp_path):
    module = load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    assert (
        module.output_path(tmp_path / "ok.json", [repo])
        == (tmp_path / "ok.json").resolve()
    )
    with pytest.raises(ValueError):
        module.output_path(repo / "nested/results/x.json", [repo])


def test_child_environment_isolates_home_config_data_and_source_path(tmp_path):
    module = load_script()
    base = tmp_path / "unit"
    base.mkdir()
    env = module._child_env(base)
    for key in ("HOME", "XDG_CONFIG_HOME", "VARDE_CONFIG_DIR", "XDG_DATA_HOME"):
        value = Path(env[key])
        assert value.is_dir()
        assert base in value.parents
    assert str(ROOT / "code/src") in env["PYTHONPATH"]
    assert str(ROOT / "core/src") in env["PYTHONPATH"]
