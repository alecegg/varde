from varde_code.quality_score.raw_measure import (
    MEASURES,
    raw_measure_sources,
    summarize,
)

SOURCE = b"""def level0(items):
    total = 0
    for item in items:
        if item > 0:
            while item:
                if item % 2:
                    total += level1(item)
                item -= 1
    return total + level1(1) + level2(1) + level3(1) + level4(1)


def level1(value):
    if value > 3:
        return level2(value) + level4(value)
    return level2(value)


def level2(value):
    if value > 2:
        return level3(value)
    return value


def level3(value):
    if value > 1:
        return level4(value)
    return value


def level4(value):
    if value:
        return value * 2
    return 0
"""


def test_raw_measures_are_non_null_for_a_call_chain() -> None:
    result = raw_measure_sources({"chain.py": SOURCE}, "python")
    rows = {row["name"]: row for row in result["functions"]}
    top = rows["level0"]
    assert top["depth"] >= 3
    assert top["fan_out"] >= 4
    assert top["tree_size"] >= 4
    assert top["max_nesting"] >= 2
    assert top["cognitive"] > 5
    assert rows["level1"]["fan_in"] >= 1
    for row in result["functions"]:
        for name in ("cognitive", "depth", "fan_out", "fan_in", "tree_size"):
            assert row[name] is not None, (row["name"], name)
        assert row["params"] >= 1
        assert row["line_span"] >= 2
    assert result["call_coverage"]["resolved"] >= 6
    assert result["structure_confidence"] in {"low", "normal"}
    assert result["summary"]["depth"]["max"] == max(r["depth"] for r in rows.values())


def test_measures_are_reported_even_when_confidence_is_low() -> None:
    source = b"def f(x):\n    return x.go() + x.stop() + x.pause()\n"
    result = raw_measure_sources({"m.py": source}, "python")
    assert result["structure_confidence"] == "low"
    assert result["functions"][0]["fan_out"] is not None
    assert result["call_coverage"]["opaque"] >= 1


def test_summary_is_deterministic_and_skips_missing_values() -> None:
    rows = [
        {"depth": 1, "x": 0},
        {"depth": None, "x": 0},
        {"depth": 3, "x": 0},
    ]
    assert raw_measure_sources({"chain.py": SOURCE}, "python") == raw_measure_sources(
        {"chain.py": SOURCE}, "python"
    )
    full = [{**dict.fromkeys(MEASURES, None), **row} for row in rows]
    assert summarize(full)["depth"] == {"min": 1, "median": 2.0, "max": 3}
    assert summarize(full)["params"] is None


FACTS_SOURCE = b'''import os


def wrapper(x):
    return inner(x)


def documented(x):
    """Only forwards."""
    inner(x)


def two_statements(x):
    y = inner(x)
    return y


def docstring_only():
    """Nothing else."""


def not_a_call(x):
    return x + 1


@decorate
def decorated(value):
    return inner(value)


def vague(data, flag):
    tmp = data
    for i in flag:
        a = i
    for item in tmp:
        pass
    return [j for j in a], os.sep


def nested_ifs(a):
    if a:
        for b in a:
            with open(b) as handle:
                if handle:
                    return 1
    return 0


def inner(x):
    return x
'''


def _rows():
    result = raw_measure_sources({"facts.py": FACTS_SOURCE}, "python")
    return {row["name"]: row for row in result["functions"]}, result


def test_delegates_counts_one_call_bodies_only() -> None:
    rows, _ = _rows()
    delegating = {"wrapper", "documented", "decorated"}
    for name, row in rows.items():
        assert row["delegates"] is (name in delegating), name


def test_vague_names_count_vague_and_single_letter_non_loop_names() -> None:
    rows, _ = _rows()
    # data, tmp, item (a vague word, even as a loop target) and a are counted;
    # the single-letter loop variables i and j are not.
    assert rows["vague"]["vague_names"] == 4
    assert rows["wrapper"]["vague_names"] == 1  # x
    assert rows["decorated"]["vague_names"] == 0
    assert rows["nested_ifs"]["vague_names"] == 1  # a (b is a loop target)


def _nested(openers: list[str]) -> bytes:
    lines = ["def f(a):"]
    for depth, opener in enumerate(openers, start=1):
        lines.append("    " * depth + opener)
    lines.append("    " * (len(openers) + 1) + "pass")
    return ("\n".join(lines) + "\n").encode()


def _nesting(openers: list[str]) -> int:
    result = raw_measure_sources({"n.py": _nested(openers)}, "python")
    return result["functions"][0]["max_nesting"]


def test_max_nesting_grows_with_nested_ifs_and_loops() -> None:
    assert [_nesting(["if a:"] * n) for n in range(1, 5)] == [0, 1, 2, 3]
    assert [_nesting(["while a:"] * n) for n in range(1, 5)] == [0, 1, 2, 3]
    # a with block adds no nesting of its own
    assert _nesting(["with a:"] * 4) == 0
    assert _nesting(["with a:", "if a:", "if a:"]) == 1


def test_file_measures_report_exact_delegation_and_token_median() -> None:
    rows, result = _rows()
    measures = result["file_measures"]["facts.py"]
    assert measures["delegation_share"] == 3 / len(rows)
    assert measures["tokens_p50"] > 0


def test_non_python_rows_have_no_python_only_facts() -> None:
    result = raw_measure_sources(
        {"a.ts": b"function f(x) { return g(x); }\nfunction g(x) { return x; }\n"},
        "typescript",
    )
    for row in result["functions"]:
        assert row["vague_names"] is None
        assert row["delegates"] is None
    assert result["file_measures"]["a.ts"]["delegation_share"] is None


def test_vague_list_equals_the_degrader() -> None:
    import importlib.util
    import sys
    from pathlib import Path

    from varde_code.quality_score.raw_measure import VAGUE_NAMES

    tools = Path(__file__).parents[3] / "code" / "bench" / "quality-corpus" / "tools"
    path = tools / "quality_degrade.py"
    if not path.exists():
        import pytest

        pytest.skip("bench corpus not available")
    sys.path.insert(0, str(tools))
    try:
        spec = importlib.util.spec_from_file_location("bench_quality_degrade", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(tools))
    assert set(module.VAGUE) == VAGUE_NAMES
