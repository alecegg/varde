# ruff: noqa: S101
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest

TOOLS = Path(__file__).parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import derive_thresholds as dt  # noqa: E402, RUF100
from varde_code.quality_score.calibration import load_calibration  # noqa: E402, RUF100

MANIFEST = """
[[repositories]]
name = "o/one"
roles = ["calibration"]
[[repositories]]
name = "o/two"
roles = ["calibration"]
[[repositories]]
name = "o/three"
roles = ["calibration"]
[[repositories]]
name = "o/held"
roles = ["held-out"]
"""


def _function(index: int, tokens: int, cognitive: int, depth: int) -> dict:
    return {
        "id": f"f{index}",
        "line": index * 10,
        "end_line": index * 10 + 5,
        "tokens": tokens,
        "params": 1,
        "cognitive": cognitive,
        "exempt_role": None,
        "fragment_scope": "file" if tokens <= 40 and index % 3 == 0 else None,
        "depth": depth,
        "fan_out": depth + 1,
        "tree_size": depth,
        "name_issues": [],
    }


def _record(repo: int, number: int) -> dict:
    functions = [
        _function(i, 20 + 25 * ((i + number + repo) % 6), (i * 3 + repo) % 14, i % 4)
        for i in range(1, 9)
    ]
    return {
        "contract": "facts-2",
        "path": f"r{repo}/m{number}.py",
        "language": "python",
        "module": f"r{repo}",
        "tokens": 150 + sum(f["tokens"] for f in functions),
        "structure_confidence": "normal",
        "unmeasured_regions": [],
        "functions": functions,
    }


def _write_facts(directory: Path, names: tuple[str, ...]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for repo, name in enumerate(names, 1):
        rows = [_record(repo, number) for number in range(1, 5)]
        (directory / f"{name}.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
    return directory


@pytest.fixture
def manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.toml"
    path.write_text(MANIFEST, encoding="utf-8")
    return path


def _plan_dir(tmp_path: Path, python_passes: bool = False) -> Path:
    plan = tmp_path / "plans/calibration"
    plan.mkdir(parents=True, exist_ok=True)
    if python_passes:
        verdict = tmp_path / "plans/resolver/notes/dev-final/verdict.md"
        verdict.parent.mkdir(parents=True, exist_ok=True)
        verdict.write_text(
            "python PASS\ntypescript FAIL\ncsharp FAIL\n", encoding="utf-8"
        )
    return plan


def _candidate(tmp_path: Path, manifest: Path, passes: bool = False) -> str:
    directory = _write_facts(tmp_path / "facts", ("o__one", "o__two", "o__three"))
    facts, digest = dt.load_facts(directory, manifest)
    return dt.build_candidate(
        facts, digest, ["python", "typescript", "csharp"], _plan_dir(tmp_path, passes)
    )


def test_repo_balanced_quantile_is_not_set_by_a_giant_repository():
    giant = [(1000, 1_000_000)]
    small = [(10, 10), (10, 10)]
    items = dt.balanced([giant, small])
    assert dt.weighted_quantile(items, 25, 100) == 10
    assert dt.weighted_quantile(items, 75, 100) == 1000
    # token-weighted pooling would give the giant repository the quantile.
    assert dt.weighted_quantile(giant + small, 25, 100) == 1000


def test_quantile_ignores_input_order():
    items = [(5, 3), (1, 1), (9, 6)]
    assert dt.weighted_quantile(items, 50, 100) == dt.weighted_quantile(
        items[::-1], 50, 100
    )


def test_candidate_loads_strictly_with_expected_identity(tmp_path, manifest):
    path = tmp_path / "cal-1-candidate.toml"
    path.write_text(_candidate(tmp_path, manifest), encoding="utf-8")
    calibration = load_calibration(path)
    assert (calibration.id, calibration.formula, calibration.validated) == (
        "cal-1",
        "vq1",
        False,
    )
    assert set(calibration.languages) >= {
        "python",
        "typescript",
        "csharp",
        "java",
        "go",
        "rust",
        "cpp",
    }
    assert all(
        not calibration.language_gating_available(name)
        for name in calibration.languages
    )


def test_output_is_identical_on_rerun(tmp_path, manifest):
    assert _candidate(tmp_path, manifest) == _candidate(tmp_path, manifest)


def test_python_thresholds_are_derived_and_ordered(tmp_path, manifest):
    data = tomllib.loads(_candidate(tmp_path, manifest))
    python = data["language"]["python"]
    assert 1 <= python["Plo"] <= python["t_frag"] <= python["Phi"]
    assert python["Phi"] != 96 or python["Plo"] != 32
    anchors = [
        python[key]
        for key in (
            "anchor_d10",
            "anchor_d50",
            "anchor_d90",
            "anchor_d99",
            "anchor_tail",
        )
    ]
    assert [float(a) for a in anchors] == sorted({float(a) for a in anchors})
    validation = data["language"]["python"]["validation"]
    assert validation["state"] == "report-only"
    assert (
        isinstance(validation["p65"], float) and validation["p10"] <= validation["p65"]
    )


def test_resolver_not_ready_marks_provisional_and_pass_clears_it(tmp_path, manifest):
    blocked = tomllib.loads(_candidate(tmp_path, manifest))
    assert blocked["language"]["python"]["validation"]["provisional"] == "resolver"
    ready = tomllib.loads(_candidate(tmp_path, manifest, passes=True))
    assert "provisional" not in ready["language"]["python"]["validation"]
    assert ready["language"]["python"]["validation"]["state"] == "report-only"
    assert ready["language"]["typescript"]["validation"]["provisional"] == "resolver"


def test_language_without_facts_and_out_of_scope_languages_keep_placeholder_values(
    tmp_path, manifest
):
    data = tomllib.loads(_candidate(tmp_path, manifest))
    placeholder = tomllib.loads(dt.PLACEHOLDER.read_text(encoding="utf-8"))
    for name in ("typescript", "csharp", "java", "go", "rust", "cpp"):
        values = {k: v for k, v in data["language"][name].items() if k != "validation"}
        original = {
            k: v for k, v in placeholder["language"][name].items() if k != "validation"
        }
        assert values == original
        assert data["language"][name]["validation"]["state"] == "report-only"
    assert "not derived" in data["language"]["typescript"]["validation"]["provenance"]
    assert data["global"] == placeholder["global"]
    assert data["limits"] == placeholder["limits"]


def test_held_out_repository_raises_before_it_is_read(tmp_path, manifest):
    directory = tmp_path / "facts"
    directory.mkdir()
    (directory / "o__held.jsonl").write_text("not json at all\n", encoding="utf-8")
    with pytest.raises(ValueError, match="held-out"):
        dt.load_facts(directory, manifest)


def test_unknown_repository_raises(tmp_path, manifest):
    directory = tmp_path / "facts"
    directory.mkdir()
    (directory / "x__stranger.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="not a manifest repository"):
        dt.load_facts(directory, manifest)


def test_command_line_writes_the_same_bytes_twice(tmp_path, manifest):
    directory = _write_facts(tmp_path / "facts", ("o__one", "o__two", "o__three"))
    plan = _plan_dir(tmp_path)
    outputs = []
    for name in ("first.toml", "second.toml"):
        out = tmp_path / name
        sys.argv = [
            "derive_thresholds.py",
            "--facts-dir",
            str(directory),
            "--manifest",
            str(manifest),
            "--plan-dir",
            str(plan),
            "--out",
            str(out),
        ]
        assert dt.main() == 0
        outputs.append(out.read_bytes())
    assert outputs[0] == outputs[1]
