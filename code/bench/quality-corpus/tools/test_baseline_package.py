# ruff: noqa: S101
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import baseline_package as bp


def make_tree(root: Path) -> tuple[Path, Path]:
    baseline = root / "baseline"
    for relative in (
        "problems/p/prompt.txt",
        "problems/p/python/test_solution.py",
        "problems/p/python/reference-stub/solution.py",
        "problems/README.md",
        "agreed/p/python/solution.py",
    ):
        path = baseline / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    cal = root / "cal-1.toml"
    cal.write_text("cal")
    return baseline, cal


def test_source_files_skip_stubs_and_readme(tmp_path) -> None:
    baseline, cal = make_tree(tmp_path)
    found = bp.source_files(baseline, cal)
    assert sorted(found) == [
        "agreed/p/python/solution.py",
        "cal-1.toml",
        "problems/p/prompt.txt",
        "problems/p/python/test_solution.py",
    ]


def test_corpus_text_is_sorted_and_compact() -> None:
    text = bp.corpus_text({"b": {"y": [3, 1]}, "a": {"x": [2, 1]}})
    assert text == '{"a":{"x":[1,2]},"b":{"y":[1,3]}}\n'


def test_write_then_drift_detects_change_missing_and_extra(tmp_path) -> None:
    baseline, cal = make_tree(tmp_path)
    sources = bp.source_files(baseline, cal)
    data = tmp_path / "data"
    bp.write(sources, data, "{}\n")
    assert bp.drift(sources, data) == []
    (data / "cal-1.toml").write_text("changed")
    (data / "problems/p/prompt.txt").unlink()
    (data / "extra.txt").write_text("x")
    assert sorted(bp.drift(sources, data)) == [
        "differs cal-1.toml",
        "missing problems/p/prompt.txt",
        "no source for extra.txt",
    ]


def test_corpus_problems(tmp_path) -> None:
    assert bp.corpus_problems(tmp_path, None) == ["missing corpus.json"]
    (tmp_path / "corpus.json").write_text("{}\n")
    assert bp.corpus_problems(tmp_path, None) == []
    assert bp.corpus_problems(tmp_path, "{}\n") == []
    assert bp.corpus_problems(tmp_path, '{"a":{}}\n') == [
        "differs corpus.json (rebuild)"
    ]
    (tmp_path / "corpus.json").write_text("not json")
    assert bp.corpus_problems(tmp_path, None) == ["corpus.json is not valid JSON"]


def test_shipped_data_matches_sources() -> None:
    sources = bp.source_files()
    assert bp.drift(sources, bp.DATA) == []
    corpus = json.loads((bp.DATA / "corpus.json").read_text())
    assert set(corpus) == {"python", "typescript", "csharp"}
