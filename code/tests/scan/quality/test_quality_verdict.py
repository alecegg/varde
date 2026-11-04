"""``varde scan`` verdict: per-file score, sd overlay, references and fix list."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from varde_code import cli_scan
from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.build import build
from varde_code.parse import parse_source
from varde_code.quality_pass.facts import quality_extractor_version
from varde_code.quality_pass.pass_ import read_facts, run_quality_pass
from varde_code.quality_score import score_scope
from varde_code.quality_score.calibration import (
    load_calibration,
    shipped_calibration_path,
)
from varde_code.quality_score.file_facts import exact_facts
from varde_code.query import modes
from varde_code.query.params import QueryError
from varde_code.scan import core, quality_verdict
from varde_code.scan.quality_scores import merge_measures

CAL = load_calibration(shipped_calibration_path())
WRAPPER_FILE = "pkg/wrappers.py"


def _clean(index: int) -> str:
    body = "".join(
        f"    for price in prices:\n        if price > {j}:\n"
        f"            subtotal = subtotal + price * discount + {j}\n"
        for j in range(5)
    )
    return (
        f"def total_price_{index}(prices, discount):\n    subtotal = 0\n"
        f"{body}    return subtotal\n"
    )


def _wrappers(compute: int = 4, wrapped: int = 3) -> str:
    out = "".join(
        f"def compute_{i}(values, scale):\n"
        f"    return [item * scale + {i} for item in values if item > {i}]\n\n\n"
        for i in range(compute)
    )
    out += "".join(
        f"def wrap_{i}(values, scale):\n"
        f"    return compute_{i % compute}(values, scale)\n\n\n"
        for i in range(wrapped)
    )
    calls = "".join(
        f"    result = result + wrap_{i}(values, scale)\n" for i in range(wrapped)
    )
    return (
        out
        + f"def run_all(values, scale):\n    result = []\n{calls}    return result\n"
    )


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        cwd=root, check=True, capture_output=True,
    )  # fmt: skip


def make_repo(root: Path, clean_files: int) -> None:
    for i in range(clean_files):
        (root / "pkg").mkdir(parents=True, exist_ok=True)
        (root / "pkg" / f"mod_{i}.py").write_text(_clean(i), encoding="utf-8")
    (root / WRAPPER_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / WRAPPER_FILE).write_text(_wrappers(), encoding="utf-8")
    build(root, CodeExtractionProvider())
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base", "--no-verify")


@pytest.fixture(autouse=True)
def _grammars(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    try:
        parse_source("python", "value\n")
    except RuntimeError as error:
        pytest.skip(f"tree-sitter grammar cache unavailable: {error}")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(modes, "_INDEX_SERVICE", None)


@pytest.fixture
def big_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    make_repo(root, 24)
    return root


@pytest.fixture
def small_repo(tmp_path: Path) -> Path:
    root = tmp_path / "small"
    make_repo(root, 3)
    return root


def _scan(root: Path, **extra) -> dict:
    return core.scan_repo({"repoRoot": str(root), **extra})


def _file(result: dict, path: str) -> dict:
    return next(f for f in result[quality_verdict.KEY]["files"] if f["path"] == path)


def test_no_verdict_without_a_request(big_repo):
    assert quality_verdict.KEY not in _scan(big_repo)
    assert quality_verdict.KEY not in _scan(big_repo, skipQuality=True, vs="repo")


def test_score_equals_score_scope_of_the_merged_record(big_repo):
    result = _scan(big_repo, vs="repo")
    record = next(r for r in merge_measures(big_repo) if r["path"] == WRAPPER_FILE)
    exact = exact_facts((big_repo / WRAPPER_FILE).read_bytes(), "python", WRAPPER_FILE)
    merged = quality_verdict.overlay_delegates(record, exact)
    micro = score_scope([merged], CAL).score
    assert micro is not None
    expected = round(float(micro.numerator / micro.denominator) / 1_000_000, 1)

    entry = _file(result, WRAPPER_FILE)
    assert entry["score"] == expected  # 0-100 tenths of the micro-point score
    assert entry["verdict"]["basis"] == "graph"
    assert result[quality_verdict.KEY]["basis"] == "graph"


def test_delegates_are_overlaid_and_change_the_score(big_repo):
    run_quality_pass(big_repo)
    record = next(r for r in merge_measures(big_repo) if r["path"] == WRAPPER_FILE)
    assert not any("delegates" in fn for fn in record["functions"])
    exact = exact_facts((big_repo / WRAPPER_FILE).read_bytes(), "python", WRAPPER_FILE)
    overlaid = quality_verdict.overlay_delegates(record, exact)
    assert sum(fn.get("delegates") is True for fn in overlaid["functions"]) == 3

    on = score_scope([overlaid], CAL).score
    off = score_scope([record], CAL).score
    assert on != off  # sd=1.0 in the shipped calibration

    version, before = quality_extractor_version(), list(read_facts(big_repo))
    _scan(big_repo, vs="repo")
    assert list(read_facts(big_repo)) == before
    assert quality_extractor_version() == version
    assert not any(
        "delegates" in fn for r in read_facts(big_repo) for fn in r["functions"]
    )


def test_verdict_fields_header_and_fix_list(big_repo):
    result = _scan(big_repo, vs="repo")
    section = result[quality_verdict.KEY]
    reference = next(r for r in section["references"] if r["language"] == "python")
    assert reference["reference_name"] == "repo (n=25)"
    assert reference["n"] == 25

    entry = _file(result, WRAPPER_FILE)
    verdict = entry["verdict"]
    assert verdict["vs"] == "repo"
    assert verdict["n"] == 24  # the judged file is left out of its own reference
    assert verdict["needs_refactor"] is True
    assert "worse_than_percent" in verdict
    assert "basis graph" in verdict["message"]
    assert entry["fixes"], "a file below its line carries a fix list"
    assert {"rank", "function", "measure", "predicted_score"} <= set(entry["fixes"][0])
    clean = _file(result, "pkg/mod_0.py")
    assert clean["fixes"] == []


def test_small_repo_gets_no_repo_verdict(small_repo):
    result = _scan(small_repo, vs="repo")
    verdict = _file(result, WRAPPER_FILE)["verdict"]
    assert "needs_refactor" not in verdict
    assert verdict["n"] == 3
    assert (
        "reference too small (n=3, need 20): no reference verdict" in verdict["message"]
    )
    assert _file(result, WRAPPER_FILE)["fixes"] == []


def test_generic_line_verdict_has_no_percentile(big_repo):
    result = _scan(big_repo, vs="generic")
    verdict = _file(result, WRAPPER_FILE)["verdict"]
    assert verdict["vs"] == "generic"
    assert "worse_than_percent" not in verdict
    assert verdict["basis"] == "graph"
    assert (
        "n not recorded"
        in result[quality_verdict.KEY]["references"][0]["reference_name"]
    )
    assert isinstance(verdict["needs_refactor"], bool)


def test_mine_without_examples_gives_no_verdict(big_repo):
    result = _scan(big_repo, vs="mine")
    verdict = _file(result, WRAPPER_FILE)["verdict"]
    assert verdict["k"] == 0
    assert "needs_refactor" not in verdict
    assert "no saved examples" in verdict["message"]


def test_changed_since_shows_only_changed_files(big_repo):
    (big_repo / "pkg" / "mod_1.py").write_text(
        _clean(1) + "\n\nX = 1\n", encoding="utf-8"
    )
    build(big_repo, CodeExtractionProvider())
    result = _scan(big_repo, changedSince="HEAD")
    assert [f["path"] for f in result[quality_verdict.KEY]["files"]] == ["pkg/mod_1.py"]
    assert result[quality_verdict.KEY]["vs"] == "repo"


def test_verdict_true_shows_all_non_test_files(big_repo):
    result = _scan(big_repo, verdict=True)
    assert len(result[quality_verdict.KEY]["files"]) == 25


def test_unknown_vs_is_rejected(big_repo):
    with pytest.raises(QueryError, match="vs must be one of"):
        _scan(big_repo, vs="bogus")


def test_help_lists_vs_and_cli_maps_it():
    assert "--vs <NAME>" in cli_scan.help("run")
    assert cli_scan._SCAN_VALUE_FLAGS["--vs"] == "vs"


def test_wrapper_heavy_file_and_equal_references_compare_consistently(tmp_path):
    root = tmp_path / "heavy"
    root.mkdir()
    (root / "pkg").mkdir()
    for i in range(24):
        (root / "pkg" / f"w_{i}.py").write_text(_wrappers(), encoding="utf-8")
    (root / WRAPPER_FILE).write_text(_wrappers(), encoding="utf-8")
    build(root, CodeExtractionProvider())
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base", "--no-verify")
    result = _scan(root, vs="repo")
    entry = _file(result, WRAPPER_FILE)
    peer = _file(result, "pkg/w_0.py")
    assert entry["score"] == peer["score"]
    # An identical file is not worse than identical peers: sd applies to both sides.
    assert entry["verdict"]["needs_refactor"] is False
    assert entry["verdict"]["worse_than_percent"] == 0


def test_unmatched_functions_are_counted_and_keep_sd_off():
    record = {"functions": [{"id": "m.py::a#1", "line": 1}]}
    shifted = {"functions": [{"id": "m.py::a#1", "line": 3, "delegates": True}]}
    renamed = {"functions": [{"id": "m.py::b#1", "line": 1, "delegates": True}]}
    for exact in (shifted, renamed):
        assert quality_verdict.unmatched_count(record, exact) == 1
        merged = quality_verdict.overlay_delegates(record, exact)
        assert "delegates" not in merged["functions"][0]
    same = {"functions": [{"id": "m.py::a#1", "line": 1, "delegates": True}]}
    assert quality_verdict.unmatched_count(record, same) == 0


def test_note_when_vs_is_asked_but_quality_is_skipped(big_repo):
    payload = _scan(big_repo, skipQuality=True, vs="repo")
    assert quality_verdict.KEY not in payload
    assert payload[quality_verdict.NOTE_KEY] == quality_verdict.SKIPPED_NOTE
    assert quality_verdict.NOTE_KEY not in _scan(big_repo, skipQuality=True)


def test_flagged_file_without_a_fix_carries_its_reason_in_a_field(
    big_repo, monkeypatch
):
    monkeypatch.setattr(quality_verdict.fix_explain, "fixes", lambda *args: [])
    entry = _file(_scan(big_repo, vs="repo"), WRAPPER_FILE)
    assert entry["fixes"] == []
    assert entry["fix_note"]
    assert entry["fix_note"] in entry["verdict"]["message"]
    assert _file(_scan(big_repo, vs="repo"), "pkg/mod_0.py").get("fix_note") is None


def test_graph_note_only_when_call_graph_structure_is_the_largest_loss():
    assert "call-graph structure" in quality_verdict.graph_note(
        {"tree_size": 50, "depth": 20, "long_side": 30}
    )
    assert quality_verdict.graph_note({"tree_size": 5, "long_side": 30}) == ""
    assert quality_verdict.graph_note({"long_side": 30}) == ""
    assert quality_verdict.graph_note({}) == ""


def test_vendored_and_benchmark_directories_are_not_in_the_verdict(tmp_path):
    root = tmp_path / "repo"
    for directory in ("pkg/externals", "benchmarks", "pkg/vendor"):
        (root / directory).mkdir(parents=True)
        (root / directory / "heavy.py").write_text(_wrappers(), encoding="utf-8")
    make_repo(root, 24)
    paths = {f["path"] for f in _scan(root, vs="repo")[quality_verdict.KEY]["files"]}
    assert WRAPPER_FILE in paths
    assert not {p for p in paths if p.endswith("heavy.py")}
