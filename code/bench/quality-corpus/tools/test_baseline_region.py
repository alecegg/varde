# ruff: noqa: S101
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import baseline_region as br

PLACEHOLDER = tomllib.loads(br.DEFAULT_CALIBRATION.read_text())
DEFAULT = {**PLACEHOLDER["language"]["python"], "p0": 3}
DEFAULT = {k: v for k, v in DEFAULT.items() if isinstance(v, int)}
CORPUS = {m: [0] * 50 + [4 * i for i in range(1, 51)] for m in br.FITTED}


def rows(value, n=5):
    return [dict.fromkeys(br.FITTED, value) for _ in range(n)]


def test_k0_equals_default():
    assert br.calibrate(DEFAULT, [], CORPUS) == dict(sorted(DEFAULT.items()))


def test_deterministic_and_order_independent():
    a, b, c = rows(2), rows(5), rows(9)
    first = br.calibrate(DEFAULT, [a, b, c], CORPUS)
    assert first == br.calibrate(DEFAULT, [a, b, c], CORPUS)
    assert list(first.items()) == list(br.calibrate(DEFAULT, [c, a, b], CORPUS).items())


def test_tighter_example_gives_lower_or_equal_thresholds():
    loose = br.calibrate(DEFAULT, [rows(8)], CORPUS)
    tight = br.calibrate(DEFAULT, [rows(2)], CORPUS)
    assert all(tight[k] <= loose[k] for k in br.FITTED.values())
    assert any(tight[k] < loose[k] for k in br.FITTED.values())


def test_clamped_to_corpus_bounds():
    lo, hi = br.corpus_bounds(CORPUS["tokens"])
    very_low = br.calibrate(DEFAULT, [rows(0)] * 10, CORPUS)
    very_high = br.calibrate(DEFAULT, [rows(10_000)] * 10, CORPUS)
    for key in br.FITTED.values():
        assert lo <= very_low[key] <= hi
        assert lo <= very_high[key] <= hi
    assert very_high["Phi"] == hi


def test_integers_only_and_keys_unchanged():
    region = br.calibrate(DEFAULT, [rows(3), rows(7)], CORPUS)
    assert set(region) == set(DEFAULT)
    assert all(type(v) is int for v in region.values())


def test_example_can_raise_by_at_most_weight_step():
    one = br.calibrate(DEFAULT, [rows(30)], CORPUS)
    for key in br.FITTED.values():
        assert one[key] - DEFAULT[key] <= (30 - DEFAULT[key]) // 3 + 1


def test_output_keys_exist_in_schema():
    region = br.calibrate(DEFAULT, [rows(3)], CORPUS)
    known = set(PLACEHOLDER["language"]["python"]) | set(br.CAL1_LANGUAGE_KEYS)
    assert set(region) <= known
    assert set(br.FITTED.values()) <= known


def test_nearest_rank_and_shift():
    assert br.nearest_rank([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == 9
    assert br.nearest_rank([], 90) is None
    assert br.shifted(10, 4, 0) == 10
    assert br.shifted(10, 4, 4) == 6
    assert br.shifted(4, 10, 1) == 6


def test_inside_region():
    region = {"c0": 5, "dp0": 3, "k0": 4, "t0": 6, "p0": 3, "Phi": 96}
    assert br.inside_region({"cognitive": 5, "params": None}, region)
    assert not br.inside_region({"cognitive": 6}, region)


def test_probe_schema_cli():
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(Path(br.__file__)), "--probe-schema"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert "schema-change: no" in result.stdout


@pytest.mark.parametrize("k", [1, 3, 8])
def test_more_agreeing_examples_move_toward_anchor(k):
    region = br.calibrate(DEFAULT, [rows(2)] * k, CORPUS)
    assert region["c0"] <= DEFAULT["c0"]
