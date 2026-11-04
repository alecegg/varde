import importlib.util
import sys
from pathlib import Path

import pytest
from varde_code.quality_score.file_advisories import (
    delegation_advisory,
    delegation_share,
    fragmentation_advisory,
    tokens_p50,
)

BENCH_TOOLS = Path(__file__).parents[3] / "code" / "bench" / "quality-corpus" / "tools"


def _row(tokens, fan_out=0, cognitive=0):
    return {"tokens": tokens, "fan_out": fan_out, "cognitive": cognitive}


def _record(*rows):
    return {"path": "pkg/mod.py", "functions": list(rows)}


FIXTURES = [
    [],
    [_row(10, 1)],
    [_row(10, 1), _row(40, 1), _row(25, 2), _row(31, 1, 3), _row(30, 1)],
    [_row(5), _row(7), _row(500, 4, 20), _row(9, 1), _row(120)],
    [_row(60), _row(90), _row(33), _row(200, 1, 2)],
    [_row(20, 1), _row(20, 1), _row(20, 1), _row(20, 1)],
]


def _bench_file_features():
    path = BENCH_TOOLS / "file_features.py"
    if not path.exists():
        pytest.skip("bench corpus not available")
    sys.path.insert(0, str(BENCH_TOOLS))
    try:
        spec = importlib.util.spec_from_file_location("bench_file_features", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(BENCH_TOOLS))
    return module.file_features


@pytest.mark.parametrize("rows", FIXTURES)
def test_ports_equal_the_bench_features(rows):
    bench = _bench_file_features()(rows)
    ported_share = delegation_share(rows)
    ported_median = tokens_p50(rows)
    if rows:
        assert ported_share is not None
        assert round(ported_share, 6) == bench["delegation_share"]
        assert ported_median == bench["tokens_p50"]
    else:
        assert ported_share is None
        assert ported_median is None


def test_delegation_fires_strictly_above_one_seventh():
    wrapper, real = _row(10, 1), _row(80, 3, 4)
    assert delegation_advisory(_record(wrapper, *[real] * 6)) is None  # exactly 1/7
    found = delegation_advisory(_record(wrapper, wrapper, *[real] * 6))
    assert found is not None
    assert found["file"] == "pkg/mod.py"
    assert found["share_percent"] == 25
    assert "`pkg/mod.py`" in found["action"]
    assert "inline" in found["action"]


def test_delegation_ignores_empty_files():
    assert delegation_advisory({"path": "a.py", "functions": []}) is None
    assert delegation_advisory({"path": "a.py"}) is None


def test_fragmentation_fires_strictly_below_the_cut():
    small = fragmentation_advisory(_record(_row(31), _row(31), _row(31)))
    assert small is not None
    assert small["median_tokens"] == 31
    assert small["file"] == "pkg/mod.py"
    assert "merge" in small["action"]
    assert fragmentation_advisory(_record(_row(32), _row(32))) is None
    assert fragmentation_advisory(_record()) is None


def _exact(delegates, tokens=80):
    return {"tokens": tokens, "fan_out": 3, "cognitive": 4, "delegates": delegates}


def test_exact_flag_overrides_the_proxy() -> None:
    proxy_hit = {**_row(10, 1), "delegates": False}
    assert delegation_share([proxy_hit]) == 0.0
    proxy_miss = {**_row(80, 3, 4), "delegates": True}
    assert delegation_share([proxy_miss]) == 1.0


def test_exact_delegation_share_ignores_rows_without_the_flag() -> None:
    from varde_code.quality_score.file_advisories import exact_delegation_share

    assert exact_delegation_share([_row(10, 1)]) is None
    assert exact_delegation_share([_exact(True), _exact(False), _row(5)]) == 0.5
    assert exact_delegation_share([]) is None


def test_delegation_advisory_uses_exact_rows_and_the_exact_cut() -> None:
    rows = [_exact(True)] * 3 + [_exact(False)] * 5
    found = delegation_advisory(_record(*rows))
    assert found is not None
    assert found["share_percent"] == 37
    # 1/7 would fire at 2 of 8, the exact cut of 1/3 does not, nor exactly 2 of 6
    assert (
        delegation_advisory(_record(*[_exact(True)] * 2, *[_exact(False)] * 6)) is None
    )
    assert (
        delegation_advisory(_record(*[_exact(True)] * 2, *[_exact(False)] * 4)) is None
    )


@pytest.mark.parametrize("path", ["src/a.ts", "Program.cs", "main.go", "x.rs"])
def test_advisories_are_python_only(path) -> None:
    wrappers = [_row(10, 1)] * 4
    assert delegation_advisory({"path": path, "functions": wrappers}) is None
    assert fragmentation_advisory({"path": path, "functions": wrappers}) is None
    assert delegation_advisory({"path": "a.pyi", "functions": wrappers}) is not None
