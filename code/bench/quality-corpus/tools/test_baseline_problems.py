# ruff: noqa: S101
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import baseline_problems as bp

RESTRICTED = bp.restricted_ids(bp.LOCK)


def copy_problems(tmp_path: Path) -> Path:
    target = tmp_path / "problems"
    shutil.copytree(bp.PROBLEMS, target)
    return target


def test_restricted_ids_come_from_lock():
    assert "retry-policy" in RESTRICTED
    assert "csv-summary" not in RESTRICTED


def test_layout_is_valid_without_running_tests():
    assert bp.check_layout(4, list(bp.LANGUAGES), RESTRICTED, run=False) == []


def test_problem_named_like_restricted_id_fails(tmp_path):
    problems = copy_problems(tmp_path)
    (problems / "notifier").rename(problems / "retry-policy")
    errors = bp.check_layout(4, list(bp.LANGUAGES), RESTRICTED, problems, run=False)
    assert "problem id retry-policy is a test-restricted id" in errors


def test_text_mentioning_restricted_id_fails(tmp_path):
    problems = copy_problems(tmp_path)
    (problems / "notifier" / "prompt.txt").write_text("A shipping quote service.\n")
    (problems / "notifier" / "api.md").write_text("see shipping_quote\n")
    errors = bp.check_layout(4, list(bp.LANGUAGES), RESTRICTED, problems, run=False)
    assert any("api.md mentions restricted id shipping-quote" in e for e in errors)


def test_more_than_eight_cases_fails(tmp_path):
    problems = copy_problems(tmp_path)
    spec = problems / "notifier" / "spec.md"
    spec.write_text(spec.read_text() + "9. one more.\n")
    errors = bp.check_layout(4, list(bp.LANGUAGES), RESTRICTED, problems, run=False)
    assert any("notifier: spec.md needs numbered cases" in e for e in errors)


def test_missing_test_file_fails(tmp_path):
    problems = copy_problems(tmp_path)
    (problems / "notifier" / "python" / "test_solution.py").unlink()
    errors = bp.check_layout(4, list(bp.LANGUAGES), RESTRICTED, problems, run=False)
    assert "notifier/python: missing test_solution.py" in errors


def test_baseline_paths_reference_no_restricted_id():
    assert bp.restricted_path_references(bp.ROOT, RESTRICTED) == []


def test_path_naming_restricted_id_is_reported(tmp_path):
    (tmp_path / "samples").mkdir()
    (tmp_path / "samples" / "Retry_Policy.py").write_text("x")
    refs = bp.restricted_path_references(tmp_path, RESTRICTED)
    assert refs == ["samples/Retry_Policy.py references restricted id retry-policy"]


def test_theme_overlap_is_listed_for_main():
    lines = bp.theme_overlaps(bp.prompts_of(), RESTRICTED)
    assert "recurring-orders ~ price-order (word order)" in lines


@pytest.mark.parametrize("language", bp.LANGUAGES)
def test_stub_fails_against_wrong_solution(language, tmp_path):
    toolchains = bp.tomllib.loads((bp.PROBLEMS / "toolchains.toml").read_text())
    tool = toolchains[language]
    if not all(shutil.which(t) for t in tool["tools"]):
        pytest.skip("toolchain missing")
    directory = bp.PROBLEMS / "notifier" / language
    broken = tmp_path / tool["solution"]
    broken.write_text("")
    ok, _ = bp.run_tests(language, broken, directory / tool["test"], toolchains)
    assert not ok


@pytest.mark.parametrize("language", bp.LANGUAGES)
def test_reference_stubs_pass(language):
    toolchains = bp.tomllib.loads((bp.PROBLEMS / "toolchains.toml").read_text())
    tool = toolchains[language]
    if not all(shutil.which(t) for t in tool["tools"]):
        pytest.skip("toolchain missing")
    errors = []
    for problem in bp.problem_ids():
        errors += bp.check_stub_runs(
            problem, bp.PROBLEMS / problem, language, toolchains
        )
    assert errors == []
