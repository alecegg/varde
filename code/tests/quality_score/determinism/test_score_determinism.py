import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

CALIBRATION = (
    Path(__file__).parents[3]
    / "src/varde_code/quality_score/calibration/placeholder.toml"
)


def _record(path: str, *, cognitive: int) -> dict[str, object]:
    return {
        "contract": "facts-2",
        "path": path,
        "language": "python",
        "module": "src",
        "tokens": 1000,
        "structure_confidence": "normal",
        "functions": [
            {
                "id": f"{path}::work",
                "line": 1,
                "tokens": 50,
                "cognitive": cognitive,
                "params": 1,
                "depth": 1,
                "fan_out": 1,
                "tree_size": 1,
                "name_issues": [],
                "fragment_scope": None,
            }
        ],
    }


def _facts_bytes(records: list[dict[str, object]], newline: str = "\n") -> bytes:
    lines = [json.dumps(record, sort_keys=True) for record in records]
    return (newline.join(lines) + newline).encode("utf-8")


def _run_score(facts: Path) -> subprocess.CompletedProcess[str]:
    script = (
        "from varde_code.quality_score.cli import run; "
        f"raise SystemExit(run(['score', '--facts', {str(facts)!r}, "
        f"'--calibration', {str(CALIBRATION)!r}, '--debug']))"
    )
    env = dict(os.environ)
    env.pop("VARDE_CALIBRATE_ALLOW_LIVE", None)
    env["PYTHONHASHSEED"] = "random"
    return subprocess.run(  # noqa: S603 - Runs the deterministic score fixture in a child process.
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_score_json_is_byte_identical_in_separate_processes(tmp_path):
    facts = tmp_path / "facts.jsonl"
    records = [_record("src/a.py", cognitive=15), _record("src/b.py", cognitive=65)]
    facts.write_bytes(_facts_bytes(records))

    first = _run_score(facts)
    second = _run_score(facts)

    assert first.returncode == second.returncode == 0
    assert first.stdout.encode("utf-8") == second.stdout.encode("utf-8")


def test_score_json_is_independent_of_facts_order(tmp_path):
    records = [
        _record("src/c.py", cognitive=25),
        _record("src/a.py", cognitive=15),
        _record("src/b.py", cognitive=65),
    ]
    outputs = []

    for index, permutation in enumerate(itertools.permutations(records)):
        facts = tmp_path / f"permutation-{index}.jsonl"
        facts.write_bytes(_facts_bytes(list(permutation)))
        result = _run_score(facts)
        assert result.returncode == 0
        outputs.append(result.stdout.encode("utf-8"))

    assert len(set(outputs)) == 1


def test_score_json_is_independent_of_facts_line_endings(tmp_path):
    records = [_record("src/a.py", cognitive=15), _record("src/b.py", cognitive=65)]
    lf_facts = tmp_path / "lf.jsonl"
    crlf_facts = tmp_path / "crlf.jsonl"
    lf_facts.write_bytes(_facts_bytes(records, "\n"))
    crlf_facts.write_bytes(_facts_bytes(records, "\r\n"))

    lf_result = _run_score(lf_facts)
    crlf_result = _run_score(crlf_facts)

    assert lf_result.returncode == crlf_result.returncode == 0
    assert lf_result.stdout.encode("utf-8") == crlf_result.stdout.encode("utf-8")
