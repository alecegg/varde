# ruff: noqa: S101
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import baseline_index_run as ir
import baseline_measure as bm
import refactor_line_eval as rle
import score_separation as ss
from varde_code.quality_score import refactor_line as rl

LIMITS = rle.limits_for(bm.DEFAULT_CALIBRATION)


def agreed_sources() -> dict[str, str]:
    return {
        f"agreed:{p.parent.parent.name}": p.read_text()
        for p in sorted(ir.AGREED_ROOT.glob("*/python/solution.py"))
    }


def school_monolith(branches: int = 30) -> str:
    body = "".join(
        f"    if value == {i}:\n        total += value * {i}\n" for i in range(branches)
    )
    return f"def process(value):\n    total = 0\n{body}    return total\n"


def test_advisory_silent_on_the_four_agreed_samples():
    sources = agreed_sources()
    assert len(sources) == 4
    assert not any(rle.advisory_flags(sources, LIMITS).values())


def test_advisory_fires_on_single_function_monoliths():
    sources = {f"draft:{n}": school_monolith(n) for n in (25, 30, 40)}
    assert all(rle.advisory_flags(sources, LIMITS).values())


def test_score_is_independent_of_the_advisory():
    source = school_monolith()
    first = bm.score_source(source, "python")["score"]
    rle.advisory_flags({"x": source}, LIMITS)
    assert bm.score_source(source, "python")["score"] == first


def test_line_equals_the_fixture_percentile_and_report_is_deterministic():
    good = [ss.Item(f"proxy:{i}", "good") for i in range(20)]
    items = [*good, ss.Item("agreed:p", "good", "p"), ss.Item("draft:p/a", "contested")]
    scores = {i.key: 70.0 + n for n, i in enumerate(items)}
    flags = {i.key: i.role == "contested" for i in items}
    ok, lines = rle.line_report(items, scores, flags)
    good_scores = [scores[i.key] for i in items if i.role == "good"]
    assert lines[0].startswith(f"refactor line X={rl.reference_line(good_scores):.1f}")
    assert ok
    assert lines == rle.line_report(items, scores, flags)[1]


def test_report_fails_when_advisory_fires_on_agreed():
    items = [ss.Item(f"proxy:{i}", "good") for i in range(9)]
    items += [ss.Item("agreed:p", "good", "p")]
    scores = {i.key: 80.0 for i in items}
    flags = {i.key: i.key == "agreed:p" for i in items}
    ok, lines = rle.line_report(items, scores, flags)
    assert not ok
    assert lines[-1] == "FAIL"
