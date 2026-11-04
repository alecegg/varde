import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest
from varde_code.quality_score.cli import run

CALIBRATION = (
    Path(__file__).parents[3]
    / "src/varde_code/quality_score/calibration/placeholder.toml"
)


def _record(path: str, *, contract: str = "facts-2") -> dict[str, object]:
    return {
        "contract": contract,
        "path": path,
        "language": "python",
        "module": "src",
        "tokens": 1000,
        "structure_confidence": "normal",
        "functions": [
            {
                "id": f"{path}::complex",
                "line": 7,
                "tokens": 50,
                "cognitive": 80,
                "params": 1,
                "depth": 1,
                "fan_out": 1,
                "tree_size": 1,
                "name_issues": ["vague", "generic"],
                "fragment_scope": None,
            }
        ],
    }


def _write_facts(path: Path, *records: dict[str, object]) -> None:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


class _IO:
    def __init__(self) -> None:
        self.stdout = StringIO()
        self.stderr = StringIO()


def _invoke(facts: Path, *options: str) -> tuple[int, str, str]:
    return _invoke_user(facts, "--debug", *options)


def _invoke_user(facts: Path, *options: str) -> tuple[int, str, str]:
    io = _IO()
    code = run(
        [
            "score",
            "--facts",
            str(facts),
            "--calibration",
            str(CALIBRATION),
            *options,
        ],
        io,
    )
    return code, io.stdout.getvalue(), io.stderr.getvalue()


def test_importing_dispatcher_does_not_import_quality_modules():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import varde_code.module; assert not any("
                "n.startswith('varde_code.quality_') for n in sys.modules)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_unknown_facts_contract_returns_cli_error(tmp_path):
    facts = tmp_path / "unknown.jsonl"
    _write_facts(facts, {"contract": "facts-9"})

    code, stdout, stderr = _invoke(facts)

    assert code == 2
    assert stdout == ""
    assert "unsupported facts contract 'facts-9' on line 1" in stderr
    assert "expected facts-1 or facts-2" in stderr


def test_facts_1_is_accepted(tmp_path):
    facts = tmp_path / "facts-1.jsonl"
    _write_facts(facts, _record("src/a.py", contract="facts-1"))

    code, stdout, stderr = _invoke(facts)

    assert code == 0, stderr
    payload = json.loads(stdout)
    assert payload["files"][0]["path"] == "src/a.py"


def test_output_is_byte_identical_across_runs(tmp_path):
    facts = tmp_path / "facts.jsonl"
    _write_facts(facts, _record("src/a.py"))

    first = _invoke(facts)
    second = _invoke(facts)

    assert first[0] == second[0] == 0
    assert first[1].encode("utf-8") == second[1].encode("utf-8")


def test_scope_filters_files_and_outputs_explain_breakdowns(tmp_path):
    facts = tmp_path / "facts.jsonl"
    _write_facts(facts, _record("src/a.py"), _record("tests/b.py"))

    code, stdout, stderr = _invoke(facts, "--scope", "src")

    assert code == 0, stderr
    payload = json.loads(stdout)
    assert payload["calibration"] == "placeholder; not validated"
    assert payload["score"] is not None
    assert payload["tokens"] == 1000
    assert [item["path"] for item in payload["files"]] == ["src/a.py"]
    assert payload["files"][0]["score"] is not None
    assert payload["files"][0]["function_values"]
    assert payload["files"][0]["breakdown"]
    names = next(item for item in payload["breakdown"] if item["name"] == "names")
    assert names["share"] > 0
    assert names["points_recoverable"] > 0
    assert names["worst_offenders"][0]["id"] == "src/a.py::complex"
    assert names["hint"]


def test_default_output_is_user_view_without_raw_fields(tmp_path):
    facts = tmp_path / "facts.jsonl"
    _write_facts(facts, _record("src/a.py"))

    raw_code, raw_out, _ = _invoke(facts)
    code, stdout, stderr = _invoke_user(facts, "--json")

    assert code == raw_code == 0, stderr
    payload = json.loads(stdout)
    assert set(payload) == {"score", "calibration", "categories", "tests_passed"}
    assert 0 <= payload["score"] <= 100
    assert payload["categories"]
    raw = json.loads(raw_out)
    raw_debt = next(c["debt"] for c in raw["breakdown"] if c["name"] == "names")
    for word in ("tokens", "debt", "value", "comfort", "worst_offenders", "files"):
        assert f'"{word}"' not in stdout
    assert str(raw_debt) not in stdout
    for word in ("tokens", "debt", "worst_offenders", "files"):
        assert f'"{word}"' in raw_out


def test_user_view_json_carries_guidance_for_the_worst_function(tmp_path):
    facts = tmp_path / "facts.jsonl"
    _write_facts(facts, _record("src/a.py"))

    code, stdout, stderr = _invoke_user(facts, "--json")

    assert code == 0, stderr
    cognitive = next(
        c for c in json.loads(stdout)["categories"] if c["name"] == "cognitive"
    )
    worst = cognitive["worst"][0]
    assert (worst["function"], worst["file"], worst["line"]) == (
        "complex",
        "src/a.py",
        7,
    )
    assert worst["now"] == 80
    assert worst["target"] == 10
    assert "`complex`" in worst["action"]


def test_default_output_is_text_with_the_same_guidance(tmp_path):
    facts = tmp_path / "facts.jsonl"
    _write_facts(facts, _record("src/a.py"))

    code, stdout, stderr = _invoke_user(facts)

    assert code == 0, stderr
    assert stdout.startswith("Score: ")
    assert "- simplify `complex` (complexity 80, limit 10)" in stdout
    assert "[src/a.py:7," in stdout


def _fn(name, line, tokens, *, cognitive=0, fan_out=0):
    return {
        "id": f"src/m.py::{name}",
        "name": name,
        "line": line,
        "tokens": tokens,
        "cognitive": cognitive,
        "params": 1,
        "depth": 1,
        "fan_out": fan_out,
        "tree_size": 1,
        "name_issues": [],
        "fragment_scope": None,
    }


def _file(*functions):
    record = _record("src/m.py")
    record["functions"] = list(functions)
    record["tokens"] = sum(fn["tokens"] for fn in functions)
    return record


def _view_for(tmp_path, record):
    facts = tmp_path / "facts.jsonl"
    _write_facts(facts, record)
    code, stdout, stderr = _invoke_user(facts, "--json")
    assert code == 0, stderr
    return json.loads(stdout), _invoke_user(facts)[1]


def test_monolith_advisory_is_in_json_and_text_and_leaves_the_score(tmp_path):
    big = _file(_fn("big", 3, 900, cognitive=30), _fn("small", 90, 100, fan_out=2))
    view, text = _view_for(tmp_path, big)
    assert view["monolith"]["function"] == "big"
    assert view["monolith"]["file"] == "src/m.py"
    assert view["monolith"]["line"] == 3
    assert "`big` holds 90% of the file" in text
    assert "Advisory (score unchanged):" in text
    plain = _file(_fn("a", 3, 500, cognitive=1), _fn("b", 90, 500, cognitive=1))
    plain_view, plain_text = _view_for(tmp_path, plain)
    assert "monolith" not in plain_view
    assert "Advisory" not in plain_text


def test_delegation_and_fragmentation_advisories_do_not_move_the_score(tmp_path):
    wrappers = _file(*(_fn(f"w{i}", i * 5, 10, fan_out=1) for i in range(1, 5)))
    view, text = _view_for(tmp_path, wrappers)
    assert view["delegation"]["share_percent"] == 100
    assert view["fragmentation"]["median_tokens"] == 10
    assert "`src/m.py`" in text
    assert text.count("Advisory (score unchanged):") == 2
    neutral = _file(*(_fn(f"n{i}", i * 5, 10, fan_out=0) for i in range(1, 5)))
    neutral_view, _ = _view_for(tmp_path, neutral)
    assert "delegation" not in neutral_view
    assert neutral_view["fragmentation"]["median_tokens"] == 10
    assert view["score"] == neutral_view["score"]


GOOD = "def add(a, b):\n    return a + b\n"
BAD = (
    "def tangle(a, b, c, d, e, f):\n"
    + "".join(
        f"    if a > {i}:\n        for x in b:\n            if x > c:\n"
        f"                a = a + x * {i}\n"
        for i in range(25)
    )
    + "    return a\n"
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        check=True,
        capture_output=True,
    )


def _file_invoke(*options: str) -> tuple[int, str, str]:
    io = _IO()
    code = run(["score", *options], io)
    return code, io.stdout.getvalue(), io.stderr.getvalue()


def _reference_file(path: Path, n: int) -> Path:
    from varde_code.quality_score.calibration import load_calibration
    from varde_code.quality_score.reference import CALIBRATION, make_reference

    calibration = load_calibration(CALIBRATION)
    reference = make_reference(
        [90.0 + i / 10 for i in range(n)],
        language="python",
        calibration=calibration,
        commit="x",
        built="command",
    )
    path.write_text(json.dumps(reference), encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "m.py").write_text(GOOD, encoding="utf-8")
    _git(root, "add", "m.py")
    _git(root, "commit", "-q", "-m", "good")
    (root / "m.py").write_text(BAD, encoding="utf-8")
    return root


def test_file_mode_fills_refactor_with_reference_and_base(repo, tmp_path):
    reference = _reference_file(tmp_path / "ref.json", 25)
    code, out, err = _file_invoke(
        "--file",
        str(repo / "m.py"),
        "--reference",
        str(reference),
        "--base",
        "HEAD",
        "--json",
    )
    assert code == 0, err
    refactor = json.loads(out)["refactor"]
    assert refactor["needs_refactor"] is True
    assert refactor["worse_than_percent"] == 100
    assert refactor["n_reference"] == 25
    assert refactor["worse_than_before"] is True
    again = _file_invoke(
        "--file",
        str(repo / "m.py"),
        "--reference",
        str(reference),
        "--base",
        "HEAD",
        "--json",
    )
    assert again[1] == out


def test_file_mode_small_reference_gives_no_verdict(repo, tmp_path):
    reference = _reference_file(tmp_path / "ref.json", 5)
    code, out, _ = _file_invoke(
        "--file", str(repo / "m.py"), "--reference", str(reference), "--json"
    )
    assert code == 0
    refactor = json.loads(out)["refactor"]
    assert "needs_refactor" not in refactor
    assert "too small" in refactor["message"]
    assert "n=5" in refactor["message"]


def test_file_mode_score_is_the_same_with_and_without_reference(repo, tmp_path):
    reference = _reference_file(tmp_path / "ref.json", 25)
    plain = json.loads(_file_invoke("--file", str(repo / "m.py"), "--json")[1])
    judged = json.loads(
        _file_invoke(
            "--file", str(repo / "m.py"), "--reference", str(reference), "--json"
        )[1]
    )
    assert "refactor" not in plain
    assert plain["score"] == judged["score"]


def test_file_mode_text_shows_n_and_report_only_label(repo, tmp_path):
    reference = _reference_file(tmp_path / "ref.json", 25)
    _, out, _ = _file_invoke(
        "--file", str(repo / "m.py"), "--reference", str(reference)
    )
    assert "not validated / report-only" in out
    relative = next(line for line in out.splitlines() if "of your reference" in line)
    assert "n=25" in relative


def test_file_mode_rejects_mismatched_options_and_calibration(repo, tmp_path):
    reference = _reference_file(tmp_path / "ref.json", 25)
    assert _file_invoke("--file", str(repo / "m.py"), "--facts", "x")[0] == 2
    assert (
        _file_invoke(
            "--facts", "x", "--calibration", str(CALIBRATION), "--base", "HEAD"
        )[0]
        == 2
    )
    code, _, err = _file_invoke(
        "--file",
        str(repo / "m.py"),
        "--calibration",
        str(CALIBRATION),
        "--reference",
        str(reference),
    )
    assert code == 2
    assert "rebuild" in err


def test_file_new_at_base_scores_without_before(repo, tmp_path):
    (repo / "new.py").write_text(BAD, encoding="utf-8")
    reference = _reference_file(tmp_path / "ref.json", 25)
    code, out, err = _file_invoke(
        "--file",
        str(repo / "new.py"),
        "--base",
        "HEAD",
        "--reference",
        str(reference),
        "--json",
    )
    assert code == 0, err
    refactor = json.loads(out)["refactor"]
    assert "worse_than_before" not in refactor
    assert "no before for this file" in refactor["message"]
    assert refactor["n_reference"] == 25


def test_unknown_base_ref_says_the_ref_is_unknown(repo):
    code, _, err = _file_invoke("--file", str(repo / "m.py"), "--base", "nonexistent")
    assert code == 2
    assert "unknown git ref" in err


def test_stored_reference_is_validated(repo, tmp_path):
    good = json.loads(_reference_file(tmp_path / "ref.json", 25).read_text())
    cases = {
        "typescript": {**good, "language": "typescript"},
        "noscores": {k: v for k, v in good.items() if k != "scores"},
        "strings": {**good, "scores": ["a", "b"]},
    }
    for name, content in cases.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(content), encoding="utf-8")
        code, _, err = _file_invoke(
            "--file", str(repo / "m.py"), "--reference", str(path)
        )
        assert code == 2, name
        assert "reference" in err and "rebuild" in err, name
        assert "Traceback" not in err
