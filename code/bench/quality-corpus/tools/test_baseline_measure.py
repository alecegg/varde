# ruff: noqa: S101
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import baseline_measure as bm

CALIBRATION = bm.load_calibration(bm.DEFAULT_CALIBRATION)

SIMPLE = """def add(a, b):
    total = a + b
    return total


def tiny(x):
    return x


def classify(values):
    result = []
    for value in values:
        if value > 10:
            if value % 2 == 0:
                result.append("big-even")
            else:
                result.append("big-odd")
        elif value > 5:
            result.append("mid")
        else:
            result.append("small")
    return result
"""

OTHER = """def parse(line):
    parts = line.split(",")
    return [part.strip() for part in parts]


def render(rows):
    out = []
    for row in rows:
        out.append(" | ".join(row))
    return "\\n".join(out)


def one(x):
    return x
"""


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return root


@pytest.fixture
def problems(tmp_path):
    a = write(
        tmp_path / "joint" / "a",
        {"solution.py": SIMPLE, "test_solution.py": "def test_x():\n    assert True\n"},
    )
    b = write(tmp_path / "joint" / "b", {"solution.py": OTHER})
    return a, b, tmp_path / "joint"


def test_measurement_is_deterministic(problems):
    a, _, _ = problems
    runs = [
        json.dumps(
            bm.report(bm.measure_directory(a, "python", CALIBRATION)), sort_keys=True
        )
        for _ in range(2)
    ]
    assert runs[0] == runs[1]


def test_test_files_are_not_measured(problems):
    a, _, _ = problems
    assert [p.name for p in bm.language_files(a, "python")] == ["solution.py"]


def test_metrics_carry_numerators_and_denominators(problems):
    a, _, _ = problems
    metrics = bm.report(bm.measure_directory(a, "python", CALIBRATION))["metrics"]
    density = metrics["debt_density"]
    assert density["denominator"] > 0
    assert (
        density["per_1k_micro"]
        == density["numerator"] * 10**9 // density["denominator"]
    )
    assert set(bm.QUANTILES) <= set(metrics)
    assert metrics["fragment_rate"]["denominator"] > 0


def test_pooling_equals_joint_measurement(problems):
    a, b, joint = problems
    parts = [bm.measure_directory(d, "python", CALIBRATION) for d in (a, b)]
    pooled = bm.pool_measurements(parts)
    joined = bm.measure_directory(joint, "python", CALIBRATION)
    assert json.dumps(pooled, sort_keys=True) == json.dumps(joined, sort_keys=True)
    assert bm.metrics_of(pooled) == bm.metrics_of(joined)


def test_pooling_survives_json_round_trip(problems):
    a, b, joint = problems
    parts = [bm.measure_directory(d, "python", CALIBRATION) for d in (a, b)]
    loaded = [json.loads(json.dumps(p)) for p in parts]
    expected = bm.metrics_of(bm.measure_directory(joint, "python", CALIBRATION))
    assert bm.metrics_of(bm.pool_measurements(loaded)) == expected


def test_pooling_rejects_mixed_languages(problems):
    a, _, _ = problems
    one = bm.measure_directory(a, "python", CALIBRATION)
    with pytest.raises(ValueError, match="cannot pool"):
        bm.pool_measurements([one, {**one, "language": "csharp"}])


def test_weighted_quantile_is_exact():
    pool = {10: 5, 20: 5}
    assert bm.weighted_quantile(pool, 50, 100) == 10
    assert bm.weighted_quantile(pool, 51, 100) == 20
    assert bm.weighted_quantile({}, 50, 100) is None


def test_fragment_rate_uses_pooled_t_frag(problems):
    *_, joint = problems
    measured = bm.measure_directory(joint, "python", CALIBRATION)
    sizes = measured["fragment_sizes"]
    t_frag = bm.metrics_of(measured)["t_frag"]
    rate = bm.metrics_of(measured)["fragment_rate"]
    assert rate["numerator"] == bm.fragment_count(sizes, t_frag)
    assert rate["denominator"] == measured["fragment_tokens"]


def test_score_source_is_whitelisted_0_to_100():
    view = bm.score_source(SIMPLE, "python")
    assert 0 <= view["score"] <= 100
    assert set(view) <= {"score", "calibration", "categories", "tests_passed", "notice"}
    assert view == bm.score_source(SIMPLE, "python")


def test_score_source_with_no_code_has_notice():
    view = bm.score_source("# nothing\n", "python")
    assert view["score"] is None
    assert view["notice"]


def test_unsupported_language_raises(tmp_path):
    with pytest.raises(ValueError, match="unsupported language"):
        bm.measure_directory(tmp_path, "go", CALIBRATION)
    with pytest.raises(ValueError, match="unsupported language"):
        bm.score_source("x", "go")


def test_cli_prints_sorted_json(problems, capsys):
    a, _, _ = problems
    assert bm.main([str(a), "--language", "python"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["metrics"]["debt_density"]["denominator"] > 0


def test_raw_flag_reports_per_function_measures(tmp_path, capsys):
    (tmp_path / "solution.py").write_text(SIMPLE)
    assert bm.main([str(tmp_path), "--language", "python", "--raw"]) == 0
    (report,) = json.loads(capsys.readouterr().out)
    assert report["files"] == 1
    assert {f["name"] for f in report["functions"]} == {"add", "tiny", "classify"}
    assert report["summary"]["cognitive"]["max"] >= 3
    assert report["call_coverage"].keys() >= {"resolved", "ambiguous", "opaque"}
