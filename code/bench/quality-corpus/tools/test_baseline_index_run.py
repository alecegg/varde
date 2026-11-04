# ruff: noqa: S101
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import baseline_index_run as ir


def test_is_candidate_excludes_tests_and_docs():
    assert ir.is_candidate("src/pkg/mod.py")
    assert not ir.is_candidate("tests/test_x.py")
    assert not ir.is_candidate("pkg/test_mod.py")
    assert not ir.is_candidate("docs/conf.py")
    assert not ir.is_candidate("pkg/mod.txt")


def test_sample_paths_is_deterministic_and_bounded():
    paths = [f"pkg/m{i}.py" for i in range(20)] + ["tests/t.py"]
    first = ir.sample_paths(paths, 5)
    assert first == ir.sample_paths(list(reversed(paths)), 5)
    assert len(first) == 5 and "tests/t.py" not in first


def test_load_drafts_extracts_fenced_code(tmp_path):
    run = tmp_path / "run1"
    run.mkdir()
    (run / "python__p__write-aposd.txt").write_text(
        "```python\ndef f(a):\n    return a\n```\n"
    )
    (run / "python__p__write-modern.txt").write_text("no code here")
    (run / "typescript__p__write-aposd.txt").write_text("```ts\nx\n```")
    drafts = ir.load_drafts([run])
    assert list(drafts) == ["p"] and list(drafts["p"]) == [("run1", "aposd")]
    assert drafts["p"][("run1", "aposd")][0]["name"] == "f"


def test_report_lists_thresholds_variants_and_ranking():
    import baseline_index_buffer as ib

    agreed = {p: [dict.fromkeys(ib.METRICS, 4) for _ in range(4)] for p in "abc"}
    drafts = {p: {("r", s): agreed[p] for s in "xy"} for p in "abc"}
    result = ib.evaluate(agreed, drafts, resamples=10)
    position = ib.corpus_position(agreed, [agreed["a"]])
    text = ir.report(result, position)
    assert "cognitive=c0 (10)" in text and "tier B ranking" in text
    assert "cognitive | A |" in text and "cognitive | B |" in text
