import random

import pytest
from audit.metrics import _graph_depths, _quantile, compute_metrics
from audit.records import validate_record


def _row(
    repo: str,
    call_class: str,
    truth: str,
    measured: str | None,
    status: str,
    **options: str | None,
) -> dict[str, object]:
    return {
        "repo": repo,
        "language": "python",
        "file": f"src/{repo}.py",
        "line": 1,
        "call_class": call_class,
        "ground_truth": truth,
        "measured_edge": measured,
        "measured_status": status,
        "truth_source": "hand_checked",
        "function_id": options.get("caller"),
        "module": options.get("module", "mod-a"),
        "ground_truth_module": options.get("truth_module", "mod-a"),
        "measured_module": options.get("measured_module", "mod-a"),
    }


def test_metrics_report_class_precision_recall_and_excluded_natural_recall() -> None:
    rows = [
        _row("a", "same_file", "f1", "f1", "resolved"),
        _row("b", "same_file", "f2", "wrong", "resolved"),
        _row("a", "imported", "f3", None, "opaque"),
        _row("b", "dynamic", "unknown", "f4", "resolved"),
        _row("a", "higher_order", "unknown", "f5", "resolved"),
    ]
    result = compute_metrics(
        rows, {"same_file": 3, "imported": 1}, bootstrap_replicates=50
    )
    assert result["per_class"]["same_file"] == {
        "sites": 2,
        "precision": 0.5,
        "recall": 0.5,
    }
    assert result["natural_frequency_recall"] == pytest.approx(0.375)
    assert result["natural_frequency_weights"] == {"same_file": 0.75, "imported": 0.25}
    assert result["unknown_sites"] == 2


def test_resolved_share_counts_unresolved_ambiguous_and_opaque_sites() -> None:
    rows = [
        _row("a", "same_file", "f1", "f1", "resolved"),
        _row("a", "same_file", "f2", None, "ambiguous"),
        _row("b", "imported", "f3", None, "opaque"),
        _row("b", "imported", "f4", None, "unresolved"),
        _row("b", "imported", "external", None, "external"),
    ]
    result = compute_metrics(rows, bootstrap_replicates=20)
    assert result["resolved_share"] == pytest.approx(1 / 4)


def test_resolved_edge_without_target_does_not_count_as_correct() -> None:
    rows = [_row("a", "same_file", "f1", None, "resolved")]
    result = compute_metrics(rows, bootstrap_replicates=2)
    assert result["precision"] == 0
    assert result["per_class"]["same_file"]["recall"] == 0


def test_bootstrap_reports_seeded_repo_cluster_intervals() -> None:
    rows = []
    for index in range(8):
        rows.append(
            _row(
                "a",
                "same_file",
                f"a{index}",
                f"a{index}",
                "resolved",
                caller=f"ca{index}",
            )
        )
        rows.append(
            _row(
                "b", "same_file", f"b{index}", "wrong", "resolved", caller=f"cb{index}"
            )
        )
    first = compute_metrics(rows, bootstrap_replicates=200, seed=31)
    second = compute_metrics(rows, bootstrap_replicates=200, seed=31)
    intervals = first["bootstrap_95"]
    assert intervals == second["bootstrap_95"]
    assert intervals["precision"] == {"lower": 0.0, "upper": 1.0}
    assert intervals["natural_frequency_recall"] == {"lower": 0.0, "upper": 1.0}
    assert intervals["resolved_share"] == {"lower": 1.0, "upper": 1.0}
    assert intervals["precision"]["upper"] - intervals["precision"]["lower"] > 0.4
    site_rng = random.Random(31)  # noqa: S311 - Deterministic test sampling is not cryptographic.
    site_samples = []
    for _ in range(200):
        draw = [site_rng.choice(rows) for _ in rows]
        site_samples.append(
            sum(row["measured_edge"] == row["ground_truth"] for row in draw) / len(draw)
        )
    site_samples.sort()
    assert intervals["precision"] != {
        "lower": _quantile(site_samples, 0.025),
        "upper": _quantile(site_samples, 0.975),
    }


def test_depth_scope_excludes_cross_module_edges_by_default() -> None:
    rows = [
        _row(
            "a",
            "same_file",
            "f2",
            "wrong",
            "resolved",
            caller="f1",
            truth_module="mod-b",
            measured_module="mod-b",
        ),
        _row("a", "same_file", "f3", "f3", "resolved", caller="f2"),
    ]
    module_scoped = compute_metrics(rows, bootstrap_replicates=2)
    all_edges = compute_metrics(rows, bootstrap_replicates=2, scope="all")
    assert module_scoped["depth_error"]["mean_absolute_error"] == 0
    assert all_edges["depth_error"]["mean_absolute_error"] == 0.5


def test_depth_error_uses_only_shared_callers_and_reports_values() -> None:
    rows = [
        _row("a", "same_file", "f2", "f2", "resolved", caller="f1"),
        _row("a", "same_file", "f3", None, "opaque", caller="f2"),
        _row("a", "same_file", "f4", "f4", "resolved", caller=None),
    ]
    result = compute_metrics(rows, bootstrap_replicates=2)["depth_error"]
    assert result == {
        "functions": 2,
        "mean_absolute_error": 1.0,
        "within_one_share": 1.0,
    }


def test_call_site_record_validation_accepts_metrics_records() -> None:
    row = _row("repo", "same_file", "f1", "f1", "resolved")
    validate_record(row)
    assert (
        compute_metrics([row], bootstrap_replicates=1)["per_class"]["same_file"][
            "sites"
        ]
        == 1
    )


def test_invalid_measured_status_is_rejected_by_validation_and_metrics() -> None:
    row = _row("repo", "same_file", "f1", None, "resolved")
    row["measured_status"] = "not-a-status"
    with pytest.raises(ValueError, match="measured_status"):
        validate_record(row)
    with pytest.raises(ValueError, match="measured_status"):
        compute_metrics([row])


def test_iterative_scc_depth_handles_long_chains_and_cycles() -> None:
    chain = {f"f{index}": {f"f{index + 1}"} for index in range(2500)}
    chain["f2500"] = set()
    depths = _graph_depths(chain)
    assert depths["f0"] == 2500
    cyclic = _graph_depths({"a": {"b"}, "b": {"a", "c"}, "c": set()})
    assert cyclic["a"] == cyclic["b"] == 1


def test_external_and_unknown_truth_values_are_distinguished() -> None:
    rows = [
        _row("a", "dynamic", "unknown", None, "opaque"),
        _row("a", "same_file", "external", None, "external"),
        _row("b", "same_file", "f1", None, "unresolved"),
    ]
    result = compute_metrics(rows, bootstrap_replicates=2)
    assert result["unknown_sites"] == 1
    assert result["external_sites"] == 1
    assert result["per_class"]["same_file"]["recall"] == 0
