import json
import subprocess
from pathlib import Path

import pytest
from varde_code.quality_score import reference
from varde_code.quality_score.calibration import load_calibration

SIMPLE = "def add(a, b):\n    return a + b\n"
BRANCHY = (
    "def decide(a, b, c):\n"
    "    if a:\n"
    "        for x in b:\n"
    "            if x and c:\n"
    "                while x > 0:\n"
    "                    x -= 1\n"
    "    return c\n"
)


def git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        check=True,
        capture_output=True,
    )


def make_repo(root: Path, files: dict[str, str]) -> Path:
    git(root, "init", "-q")
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "init", "--allow-empty")
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(
        tmp_path,
        {
            "pkg/c.py": BRANCHY,
            "pkg/a.py": SIMPLE,
            "pkg/b.py": SIMPLE + "\n" + BRANCHY,
            "tests/test_a.py": SIMPLE,
            "vendor/lib.py": BRANCHY,
            "pkg/test_b.py": BRANCHY,
        },
    )


def test_build_twice_gives_identical_json(repo: Path) -> None:
    first = json.dumps(reference.build(repo, "python"), sort_keys=True)
    second = json.dumps(reference.build(repo, "python"), sort_keys=True)
    assert first == second


def test_records_n_and_calibration_provenance(repo: Path) -> None:
    built = reference.build(repo, "python")
    calibration = load_calibration(reference.CALIBRATION)
    assert built["n"] == 3
    assert built["scores"] == sorted(built["scores"])
    assert built["calibration_id"] == "cal-2"
    assert built["calibration_sha256"] == calibration.source_sha256
    assert built["language"] == "python"
    assert len(built["commit"]) == 40
    assert built["built"] == "command"


def test_tests_generated_and_vendored_paths_are_excluded() -> None:
    paths = ["a.py", "tests/t.py", "test_x.py", "x_test.py", "vendor/v.py", "app.py"]
    assert reference.eligible_paths(paths, 10) == ["a.py", "app.py"]


def test_cap_strides_over_sorted_paths_and_covers_late_directories() -> None:
    paths = [f"d{i:02d}/m.py" for i in range(100)][::-1]
    chosen = reference.eligible_paths(paths, 10)
    assert chosen == reference.eligible_paths(sorted(paths), 10)
    assert len(chosen) == 10
    assert chosen == sorted(chosen)
    assert chosen[0] == "d00/m.py"
    assert chosen[-1] >= "d90/m.py"


def test_under_cap_keeps_all_sorted() -> None:
    assert reference.eligible_paths(["c.py", "a.py", "b.py"], 5) == [
        "a.py",
        "b.py",
        "c.py",
    ]


def test_confidence_levels() -> None:
    assert [reference.confidence(n) for n in (19, 20, 49, 50)] == [
        "insufficient",
        "low",
        "low",
        "ok",
    ]


def test_cap_limits_n(repo: Path) -> None:
    assert reference.build(repo, "python", cap=2)["n"] == 2


def test_auto_equals_command_except_built(repo: Path) -> None:
    command = reference.build(repo, "python")
    auto = reference.load_or_build(repo, "python")
    assert auto["built"] == "auto"
    assert {**auto, "built": "command"} == command


def test_load_or_build_reads_the_stored_file(repo: Path, tmp_path: Path) -> None:
    stored = reference.build(repo, "python")
    stored["scores"] = [1.0]
    stored["n"] = 1
    path = repo / ".varde" / "quality" / "reference-python.json"
    reference.write(stored, path)
    assert reference.load_or_build(repo, "python") == stored


def test_empty_repo_raises_a_clear_error(tmp_path: Path) -> None:
    make_repo(tmp_path, {"README.md": "hello\n"})
    with pytest.raises(reference.ReferenceError, match="no scorable python source"):
        reference.build(tmp_path, "python")


def test_benchmark_and_vendored_directories_are_not_reference_paths() -> None:
    from varde_code.quality_score.reference import is_reference_path

    assert is_reference_path("pkg/utils/_response.py")
    for path in (
        "asv_benchmarks/benchmarks/svm.py",
        "pkg/bench/run.py",
        "sklearn/externals/array_api_compat/fft.py",
        "pkg/vendor/lib.py",
        "tests/test_a.py",
    ):
        assert not is_reference_path(path)
    assert is_reference_path("pkg/benchmarks.py")
