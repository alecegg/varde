"""mutate_check behaviour: accounting, exit codes, and the random-only switch."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"
SCRIPT = TOOLS / "mutate_check.py"
ENV_NAME = "SAMPLE_RANDOM_ONLY"
VARIANT = "def answer():\n    return 42\n\n\ndef scaled(n):\n    return n * 2\n"


def write_item(root: Path, test: str) -> Path:
    item = root / "item"
    item.mkdir()
    (item / "sensible.py").write_text(VARIANT)
    (item / "behaviour_test.py").write_text(test)
    return item


def write_spec(root: Path, body: str) -> Path:
    path = root / "mutants.toml"
    path.write_text(body)
    return path


def mutant(identifier: str, find: str, replace: str, extra: str = "") -> str:
    return (
        "[[mutants]]\n"
        f'id = "{identifier}"\n'
        f'description = "{identifier} mutant"\n'
        f"find = '{find}'\n"
        f"replace = '{replace}'\n"
        f"{extra}\n"
    )


def run_tool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - Runs the mutation checker CLI against fixture data.
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def env_test() -> str:
    return (
        "import os\n\nimport solution\n\n"
        f'if not os.environ.get("{ENV_NAME}"):\n'
        "    assert solution.answer() == 42\n\n"
        "for n in range(20):\n"
        "    assert solution.scaled(n) == 2 * n\n"
    )


def argv_test() -> str:
    return (
        "import sys\n\nimport solution\n\n"
        'if "--random-only" not in sys.argv:\n'
        "    assert solution.answer() == 42\n\n"
        "for n in range(20):\n"
        "    assert solution.scaled(n) == 2 * n\n"
    )


def test_accounting_reports_killed_survived_unapplied_and_equivalent(
    tmp_path: Path,
) -> None:
    item = write_item(tmp_path, env_test())
    spec = write_spec(
        tmp_path,
        mutant("answer-wrong", "return 42", "return 43")
        + mutant("scaled-reordered", "return n * 2", "return 2 * n")
        + mutant("stale-find", "not in the variant", "nothing")
        + mutant(
            "double-is-twice",
            "return n * 2",
            "return n + n",
            "equivalent = true\nreason = '2 * n equals n + n for every integer n'\n",
        ),
    )
    result = run_tool(
        "--item",
        str(item),
        "--variant",
        "sensible.py",
        "--mutants",
        str(spec),
        "--json",
    )
    report = json.loads(result.stdout)
    assert result.returncode == 1
    assert report["status"] == "failed"
    assert (report["mutants"], report["killed"], report["survived"]) == (4, 1, 1)
    assert (report["unapplied"], report["equivalent"]) == (1, 1)
    assert report["survivors"] == [
        {"id": "scaled-reordered", "description": "scaled-reordered mutant"}
    ]
    assert report["unapplied_mutants"] == [
        {"id": "stale-find", "detail": "find text does not occur exactly once"}
    ]


def test_exit_zero_when_every_mutant_is_killed_or_equivalent(tmp_path: Path) -> None:
    item = write_item(tmp_path, env_test())
    spec = write_spec(
        tmp_path,
        mutant("answer-wrong", "return 42", "return 43")
        + mutant("scaled-tripled", "return n * 2", "return n * 3")
        + mutant(
            "double-is-twice",
            "return n * 2",
            "return n + n",
            "equivalent = true\nreason = '2 * n equals n + n for every integer n'\n",
        ),
    )
    result = run_tool(
        "--item",
        str(item),
        "--variant",
        "sensible.py",
        "--mutants",
        str(spec),
        "--json",
    )
    report = json.loads(result.stdout)
    assert result.returncode == 0
    assert report["status"] == "passed"
    assert (report["killed"], report["equivalent"]) == (2, 1)


def test_find_text_must_occur_exactly_once(tmp_path: Path) -> None:
    item = write_item(tmp_path, env_test())
    spec = write_spec(
        tmp_path, mutant("repeated", "    return ", "    raise ValueError()")
    )
    result = run_tool(
        "--item", str(item), "--variant", "sensible.py", "--mutants", str(spec)
    )
    assert result.returncode == 1
    assert "0 killed, 0 survived, 0 broken, 1 unapplied" in result.stdout
    assert "unapplied repeated: find text does not occur exactly once" in result.stdout


def test_build_failure_is_broken_rather_than_killed(tmp_path: Path) -> None:
    item = write_item(tmp_path, env_test())
    spec = write_spec(tmp_path, mutant("syntax-error", "return n * 2", "return n **"))
    result = run_tool(
        "--item",
        str(item),
        "--variant",
        "sensible.py",
        "--mutants",
        str(spec),
        "--json",
    )
    report = json.loads(result.stdout)
    assert result.returncode == 1
    assert report["status"] == "failed"
    assert (report["killed"], report["broken"], report["survived"]) == (0, 1, 0)
    assert report["broken_mutants"][0]["id"] == "syntax-error"
    assert report["broken_mutants"][0]["allowed"] is False


def test_allow_broken_accepts_a_build_failure(tmp_path: Path) -> None:
    item = write_item(tmp_path, env_test())
    spec = write_spec(
        tmp_path,
        mutant("syntax-error", "return n * 2", "return n **", "allow_broken = true\n"),
    )
    result = run_tool(
        "--item",
        str(item),
        "--variant",
        "sensible.py",
        "--mutants",
        str(spec),
        "--json",
    )
    report = json.loads(result.stdout)
    assert result.returncode == 0
    assert report["status"] == "passed"
    assert (report["broken"], report["killed"]) == (1, 0)
    assert report["broken_mutants"][0]["allowed"] is True


def test_random_only_uses_the_declared_environment_switch(tmp_path: Path) -> None:
    item = write_item(tmp_path, env_test())
    spec = write_spec(
        tmp_path,
        f'[run]\npython = {{ env = "{ENV_NAME}" }}\n\n'
        + mutant("answer-wrong", "return 42", "return 43")
        + mutant("scaled-tripled", "return n * 2", "return n * 3"),
    )
    full = run_tool(
        "--item", str(item), "--variant", "sensible.py", "--mutants", str(spec)
    )
    random_only = run_tool(
        "--item",
        str(item),
        "--variant",
        "sensible.py",
        "--mutants",
        str(spec),
        "--random-only",
    )
    assert full.returncode == 0
    assert "2 killed" in full.stdout
    assert random_only.returncode == 1
    assert "1 killed, 1 survived" in random_only.stdout
    assert "survived answer-wrong: answer-wrong mutant" in random_only.stdout


def test_random_only_uses_the_declared_filter_command(tmp_path: Path) -> None:
    item = write_item(tmp_path, argv_test())
    spec = write_spec(
        tmp_path,
        '[run]\npython = { command = ["python3", "{test}", "--random-only"] }\n\n'
        + mutant("answer-wrong", "return 42", "return 43")
        + mutant("scaled-tripled", "return n * 2", "return n * 3"),
    )
    result = run_tool(
        "--item",
        str(item),
        "--variant",
        "sensible.py",
        "--mutants",
        str(spec),
        "--random-only",
    )
    assert result.returncode == 1
    assert "1 survived" in result.stdout
    assert "survived answer-wrong" in result.stdout


def test_random_only_without_a_run_entry_is_a_usage_error(tmp_path: Path) -> None:
    item = write_item(tmp_path, env_test())
    spec = write_spec(tmp_path, mutant("answer-wrong", "return 42", "return 43"))
    result = run_tool(
        "--item",
        str(item),
        "--variant",
        "sensible.py",
        "--mutants",
        str(spec),
        "--random-only",
    )
    assert result.returncode == 2
    assert "[run] python" in result.stderr


def test_missing_argument_is_a_usage_error() -> None:
    result = run_tool("--variant", "sensible.py")
    assert result.returncode == 2
    assert "--item" in result.stderr
