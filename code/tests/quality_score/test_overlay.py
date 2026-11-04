import importlib.util
from pathlib import Path

import pytest
from varde_code.quality_score.baseline_tests import LANGUAGES
from varde_code.quality_score.calibration import load_calibration
from varde_code.quality_score.calibration import overlay as ov
from varde_code.quality_score.cli.baseline_service import score_code

CAL1 = Path(ov.__file__).parent / "cal-1.toml"
BENCH_REGION = (
    Path(__file__).resolve().parents[3]
    / "code/bench/quality-corpus/tools/baseline_region.py"
)
NESTED = (
    "def add(a, b):\n"
    + "".join("    " * (i + 1) + f"if a > {i}:\n" for i in range(8))
    + "    " * 9
    + "return a + b\n    return 0\n"
)
assert "python" in LANGUAGES


@pytest.fixture(scope="module")
def parent():
    return load_calibration(CAL1)


def rows(**values):
    return [dict.fromkeys(ov.FITTED, 1) | values]


def test_zero_examples_keep_the_default(parent) -> None:
    default = ov.default_region(parent, "python")
    assert ov.calibrate(default, [], {"cognitive": [1, 50]}) == default


def test_calibrate_moves_toward_examples_and_clamps(parent) -> None:
    default = ov.default_region(parent, "python")
    moved = ov.calibrate(default, [rows(cognitive=30)] * 4, {})
    assert moved["c0"] > default["c0"]
    assert moved["c0"] == 24  # 12 + 4/6 * (30 - 12)
    clamped = ov.calibrate(default, [rows(cognitive=30)] * 4, {"cognitive": [5, 20]})
    assert clamped["c0"] == 20


def test_calibrate_equals_the_bench_derivation(parent) -> None:
    if not BENCH_REGION.is_file():
        pytest.skip("bench tools not present")
    spec = importlib.util.spec_from_file_location("baseline_region", BENCH_REGION)
    assert spec is not None and spec.loader is not None
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    default = ov.default_region(parent, "python")
    examples = [rows(cognitive=c, depth=d, tokens=c * 9) for c, d in ((9, 2), (30, 5))]
    corpus = {"cognitive": [2, 8, 15, 40], "tokens": [30, 100, 300]}
    assert ov.calibrate(default, examples, corpus) == bench.calibrate(
        default, examples, corpus
    )


def make_overlay(parent, **metrics):
    sample = ov.Sample("adder", "ab" * 32, "adder.py")
    thresholds = ov.default_region(parent, "python") | metrics
    return ov.build_overlay(
        parent, "python", [sample], thresholds, "2026-10-31T00:00:00Z"
    )


def test_overlay_records_parent_user_code_and_baseline(parent) -> None:
    overlay = make_overlay(parent, c0=40)
    read = ov.read_overlay(ov.render_overlay(overlay), parent)
    assert read == overlay
    assert read.source == "custom"
    assert (read.parent_id, read.parent_sha256) == ("cal-2", parent.source_sha256)
    assert read.samples[0].code_sha256 == "ab" * 32
    assert read.metrics["c0"] == 40
    assert "c0" not in read.inherited
    assert "dp0" in read.inherited


def test_wrong_parent_hash_raises(parent) -> None:
    text = ov.render_overlay(make_overlay(parent)).replace(
        parent.source_sha256, "0" * 64
    )
    with pytest.raises(ov.OverlayError, match="parent_sha256"):
        ov.read_overlay(text, parent)


def test_unknown_keys_raise(parent) -> None:
    text = ov.render_overlay(make_overlay(parent))
    with pytest.raises(ov.OverlayError, match="unknown overlay keys"):
        ov.read_overlay("extra = 1\n" + text, parent)
    with pytest.raises(ov.OverlayError, match="unknown overlay metrics"):
        ov.read_overlay(text + "bogus = 3\n", parent)
    with pytest.raises(ov.OverlayError, match="sample"):
        ov.read_overlay(text.replace("code_path", "path"), parent)


def test_effective_calibration_scores_like_the_equivalent_cal1(
    parent, tmp_path
) -> None:
    effective = ov.effective_calibration(parent, make_overlay(parent, c0=40))
    text = CAL1.read_text()
    assert text.count("c0 = 12\n") == 1
    edited = tmp_path / "cal-1.toml"
    edited.write_text(text.replace("c0 = 12\n", "c0 = 40\n"))
    equivalent = load_calibration(edited)
    assert (
        effective.languages["python"].parameters
        == equivalent.languages["python"].parameters
    )
    assert (
        score_code(NESTED, "python", effective, None, False)["score"]
        == score_code(NESTED, "python", equivalent, None, False)["score"]
    )
    base = score_code(NESTED, "python", parent, None, False)["score"]
    assert score_code(NESTED, "python", effective, None, False)["score"] > base


def test_unchanged_thresholds_score_like_the_parent(parent) -> None:
    effective = ov.effective_calibration(parent, make_overlay(parent))
    assert score_code(NESTED, "python", effective, None, False) == score_code(
        NESTED, "python", parent, None, False
    )


@pytest.mark.parametrize(
    "code_path", ["../escape.py", "sub/adder.py", "..\\escape.py", "..", "/etc/passwd"]
)
def test_sample_code_path_must_be_a_bare_file_name(parent, code_path) -> None:
    text = ov.render_overlay(make_overlay(parent)).replace(
        'code_path = "adder.py"',
        f'code_path = "{code_path.replace(chr(92), chr(92) * 2)}"',
    )
    with pytest.raises(ov.OverlayError, match="bare file name"):
        ov.read_overlay(text, parent)
