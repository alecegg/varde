import ast
import json
import subprocess
from io import StringIO
from pathlib import Path

import pytest
from varde_code.quality_score import vs
from varde_code.quality_score.calibration import load_calibration
from varde_code.quality_score.calibration import overlay as ov
from varde_code.quality_score.cli import run
from varde_code.quality_score.refactor_line import needs_refactor
from varde_code.quality_score.reference import CALIBRATION, make_reference

BAD = (
    "def tangle(a, b, c, d, e, f):\n"
    + "".join(
        f"    if a > {i}:\n        for x in b:\n            if x > c:\n"
        f"                a = a + x * {i}\n"
        for i in range(25)
    )
    + "    return a\n"
)
GOOD = "def add(a, b):\n    return a + b\n"


class _IO:
    def __init__(self) -> None:
        self.stdout = StringIO()
        self.stderr = StringIO()


def _score(*options: str) -> tuple[int, str, str]:
    io = _IO()
    code = run(["score", *options], io)
    return code, io.stdout.getvalue(), io.stderr.getvalue()


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        check=True,
        capture_output=True,
    )


@pytest.fixture
def config(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "config"
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(path))
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "bad.py").write_text(BAD, encoding="utf-8")
    (root / "good.py").write_text(GOOD, encoding="utf-8")
    (root / "t.java").write_text("class T { void f() { } }\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _reference_file(path: Path, n: int) -> Path:
    reference = make_reference(
        [90.0 + i / 10 for i in range(n)],
        language="python",
        calibration=load_calibration(CALIBRATION),
        commit="x",
        built="command",
    )
    path.write_text(json.dumps(reference), encoding="utf-8")
    return path


def _save_overlay(config: Path, count: int) -> None:
    parent = load_calibration(CALIBRATION)
    samples = [ov.Sample(f"p{i}", "ab" * 32, f"p{i}.py") for i in range(count)]
    overlay = ov.build_overlay(
        parent,
        "python",
        samples,
        ov.default_region(parent, "python"),
        "2026-10-31T00:00:00Z",
    )
    quality = config / "quality"
    quality.mkdir(parents=True)
    (quality / "overlay-python.toml").write_text(ov.render_overlay(overlay))


def test_needs_refactor_is_strictly_below() -> None:
    assert needs_refactor(70.0, 76.2) is True
    assert needs_refactor(76.2, 76.2) is False


def test_default_output_equals_vs_repo(repo, tmp_path) -> None:
    file = str(repo / "bad.py")
    ref_file = str(_reference_file(tmp_path / "r.json", 25))
    auto = _score("--file", file, "--reference", "auto", "--json")
    assert auto == _score("--file", file, "--vs", "repo", "--json")
    with_ref = _score("--file", file, "--reference", ref_file, "--json")
    assert with_ref == _score(
        "--file", file, "--vs", "repo", "--reference", ref_file, "--json"
    )


def test_repo_header_names_reference_basis_and_n(repo, tmp_path) -> None:
    ref_file = _reference_file(tmp_path / "r.json", 25)
    _, out, _ = _score(
        "--file", str(repo / "bad.py"), "--reference", str(ref_file), "--json"
    )
    refactor = json.loads(out)["refactor"]
    assert refactor["basis"] == "file-only"
    assert refactor["n"] == 25
    assert refactor["message"].startswith("vs repo (n=25), basis file-only:")
    assert refactor["worse_than_percent"] == 100


def test_generic_gives_line_verdict_without_percent(repo) -> None:
    code, out, err = _score("--file", str(repo / "bad.py"), "--vs", "generic", "--json")
    assert code == 0, err
    refactor = json.loads(out)["refactor"]
    assert refactor["needs_refactor"] is True
    assert refactor["basis"] == "file-only"
    assert refactor["k"] is None
    assert "n not recorded" in refactor["reference_name"]
    assert "basis file-only" in refactor["message"]
    assert "worse_than_percent" not in refactor
    above = vs.verdict(
        vs.generic_reference(load_calibration(CALIBRATION), "python"), 95.0
    )
    assert above["needs_refactor"] is False
    assert "worse_than_percent" not in above


def test_generic_for_uncalibrated_language_gives_no_verdict() -> None:
    parent = load_calibration(CALIBRATION)
    for language in ("java", "go", "rust", "cpp"):
        reference = vs.generic_reference(parent, language)
        result = vs.verdict(reference, 50.0)
        assert reference.line is None
        assert "needs_refactor" not in result
        assert f"generic not calibrated for {language}" in result["message"]
    assert vs.generic_reference(parent, "python").line is not None


def test_mine_without_examples_points_to_the_baseline_page(repo, config) -> None:
    code, out, err = _score("--file", str(repo / "bad.py"), "--vs", "mine", "--json")
    assert code == 0, err
    refactor = json.loads(out)["refactor"]
    assert "needs_refactor" not in refactor
    assert refactor["k"] == 0
    assert "k=0" in refactor["message"]
    assert "varde code quality baseline ui" in refactor["message"]


def test_mine_k_equals_saved_sample_count(repo, config) -> None:
    _save_overlay(config, 3)
    code, out, err = _score("--file", str(repo / "bad.py"), "--vs", "mine", "--json")
    assert code == 0, err
    refactor = json.loads(out)["refactor"]
    assert refactor["k"] == 3
    assert refactor["reference_name"] == "your examples (k=3)"
    assert "needs_refactor" in refactor
    assert "worse_than_percent" not in refactor
    text = _score("--file", str(repo / "bad.py"), "--vs", "mine")[1]
    assert "vs your examples (k=3), basis file-only" in text


def test_vs_conflicts_are_exit_2(repo, tmp_path) -> None:
    ref_file = str(_reference_file(tmp_path / "r.json", 25))
    code, _, err = _score(
        "--file", str(repo / "bad.py"), "--vs", "generic", "--reference", ref_file
    )
    assert code == 2
    assert "--reference is for --vs repo" in err
    facts = tmp_path / "f.jsonl"
    facts.write_text("", encoding="utf-8")
    code, _, err = _score(
        "--facts", str(facts), "--calibration", str(CALIBRATION), "--vs", "repo"
    )
    assert code == 2
    assert "--vs needs --file" in err


@pytest.mark.parametrize("name", ["generic", "mine"])
def test_base_with_line_reference_is_exit_2(repo, name) -> None:
    code, _, err = _score(
        "--file", str(repo / "bad.py"), "--vs", name, "--base", "HEAD"
    )
    assert code == 2
    assert f"--base is for --vs repo, not --vs {name}" in err


def test_vs_module_imports_no_label_reader() -> None:
    tree = ast.parse(Path(vs.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert imported <= {
        "__future__",
        "dataclasses",
        "typing",
        "calibration",
        "fixedpoint.arithmetic",
        "refactor_line",
        "cli.baseline_service",
    }
    names = {
        a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names
    }
    assert not {n for n in names if "label" in n.lower() or "accept" in n.lower()}
