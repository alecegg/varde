import json
import subprocess
import sys
from pathlib import Path

import pytest

PERF = Path(__file__).resolve().parents[2] / "perf"
sys.path.insert(0, str(PERF))
import stats  # noqa: E402


def result(wall: float, rss: float) -> dict:
    return {
        "results": {
            "tiny": {"cold": {"wall_ms_median": wall, "peak_rss_bytes_median": rss}}
        }
    }


def run_compare(tmp_path: Path, time_ratio: float, memory_ratio: float) -> int:
    base, final = tmp_path / "b.json", tmp_path / "f.json"
    base.write_text(json.dumps(result(100.0, 1000.0)))
    final.write_text(json.dumps(result(100.0 * time_ratio, 1000.0 * memory_ratio)))
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(PERF / "compare.py"), str(base), str(final)],
        capture_output=True,
        check=False,
    )
    return proc.returncode


@pytest.mark.parametrize(
    ("time_ratio", "memory_ratio", "code"),
    [(1.04, 1.0, 0), (1.06, 1.0, 1), (1.0, 1.4, 0), (1.0, 1.6, 1), (1.06, 1.6, 1)],
)
def test_compare_exit_codes(tmp_path, time_ratio, memory_ratio, code):
    assert run_compare(tmp_path, time_ratio, memory_ratio) == code


def test_summarize_needs_runs():
    with pytest.raises(ValueError):
        stats.summarize([])


def test_summarize_medians():
    rows = [{"wall_ms": w, "peak_rss_bytes": w * 10} for w in (3, 1, 2)]
    summary = stats.summarize(rows)
    assert summary["wall_ms_median"] == 2
    assert summary["peak_rss_bytes_max"] == 30


def test_rss_units():
    assert stats.rss_bytes(5, "darwin") == 5
    assert stats.rss_bytes(5, "linux") == 5120


def test_missing_scenario_raises():
    with pytest.raises(ValueError):
        stats.ratios(result(1, 1), {"results": {"tiny": {}}})
