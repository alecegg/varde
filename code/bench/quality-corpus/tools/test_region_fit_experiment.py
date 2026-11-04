# ruff: noqa: S101
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import baseline_region as br
import region_fit_experiment as rfe

PLACEHOLDER = tomllib.loads(br.DEFAULT_CALIBRATION.read_text())
DEFAULT = {
    k: v
    for k, v in {**PLACEHOLDER["language"]["python"], "p0": 3}.items()
    if isinstance(v, int)
}
CORPUS = {m: [0] * 50 + [4 * i for i in range(1, 51)] for m in br.FITTED}


def sample(values):
    return [dict.fromkeys(br.FITTED, v) for v in values]


def test_mad_anchor_uses_scaled_mad():
    # median 10, |dev| = 0,0,0,2,2 -> MAD 0 ; widen the spread to get MAD 2
    assert rfe.mad_anchor([10, 10, 10, 8, 12]) == 10
    assert rfe.mad_anchor([8, 9, 10, 11, 12]) == 10 + (3 * 14826 * 1 + 5000) // 10000
    assert rfe.mad_anchor([]) is None


def test_tukey_and_trimmed_anchors():
    values = list(range(1, 101))
    assert rfe.tukey_anchor(values) == 75 + (3 * 50 + 1) // 2
    assert rfe.trimmed_anchor(values) == 86  # q90 of the lowest 95 values
    assert rfe.trimmed_anchor([]) is None


def test_per_file_anchor_ignores_one_outlier_file():
    files = [[1, 2, 3, 4], [1, 2, 3, 5], [100, 200, 300, 400]]
    assert rfe.per_file_anchor(files) == 5
    assert rfe.anchor("q90", files) == 300


def test_shifted_q90_matches_baseline_calibrate():
    examples = [sample([2, 4, 9]), sample([3, 5, 7]), sample([1, 6, 8])]
    expected = br.calibrate(DEFAULT, examples, CORPUS)
    assert rfe.fit_region(DEFAULT, examples, CORPUS, "q90", True) == expected


def test_raw_fit_is_clamped_and_k0_returns_default():
    examples = [sample([500, 600, 700])]
    region = rfe.fit_region(DEFAULT, examples, CORPUS, "q90", False)
    assert region["c0"] == br.nearest_rank(CORPUS["cognitive"], 99)
    assert rfe.fit_region(DEFAULT, [], CORPUS, "mad3", True) == dict(
        sorted(DEFAULT.items())
    )


def test_unknown_method_raises():
    try:
        rfe.anchor("nope", [[1]])
    except ValueError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("expected ValueError")
