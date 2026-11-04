"""Ranked fixes: fields, ordering, advisory entries and the re-score oracle.

The oracle applies a real source edit, re-extracts with ``exact_facts`` and
scores with the same scorer, independent of the facts-level predictor.
"""

import ast
import json
from io import StringIO
from pathlib import Path

import pytest
from varde_code.quality_score import fix_explain
from varde_code.quality_score.calibration import load_calibration
from varde_code.quality_score.cli import run
from varde_code.quality_score.file_facts import exact_facts
from varde_code.quality_score.reference import CALIBRATION, score_of_facts

CAL = load_calibration(CALIBRATION)
# Measured on the 7 split and 8 wrapper fixtures below: largest |predicted - real|
# was 0.2 points (split) and 0.0 (wrapper); the tolerance leaves 0.3 of slack.
TOLERANCE = 0.5
FIELDS = {
    "rank",
    "file",
    "line",
    "function",
    "measure",
    "advisory",
    "contribution_points",
    "distance_to_line",
    "change",
    "predicted_score",
}
OTHER = (
    "def clamp_value(value, low, high):\n    return max(low, min(value, high))\n\n\n"
    "def parse_line(text):\n    return [int(part) for part in text.split(',')]\n\n\n"
)


def _score(record) -> float:
    value = score_of_facts(record, CAL)
    assert value is not None
    return value


def _facts(source: str, path: str = "m.py", language: str = "python"):
    return exact_facts(source, language, path)


def _body(count: int) -> str:
    return "".join(
        f"    total = total + sum(item * {i} for item in values if item > {i})\n"
        f"    if total > {i + 100}:\n        total = total - {i}\n"
        for i in range(count)
    )


def _long(count: int) -> str:
    head = "def process_batch(values):\n    total = 0\n"
    return f"{OTHER}{head}{_body(count)}    return total\n"


def _split(count: int) -> str:
    half = count // 2
    return (
        f"{OTHER}def process_batch_tail(values, total):\n{_body(count - half)}"
        "    return total\n\n\n"
        f"def process_batch(values):\n    total = 0\n{_body(half)}"
        "    return process_batch_tail(values, total)\n"
    )


def _wrappers(compute: int, wrapped: int, drop: int | None) -> str:
    out = "".join(
        f"def compute_{i}(values, scale):\n"
        f"    return [item * scale + {i} for item in values if item > {i}]\n\n\n"
        for i in range(compute)
    )
    out += "".join(
        f"def wrap_{i}(values, scale):\n"
        f"    return compute_{i % compute}(values, scale)\n\n\n"
        for i in range(wrapped)
        if i != drop
    )
    callee = {i: f"wrap_{i}" for i in range(wrapped)}
    if drop is not None:
        callee[drop] = f"compute_{drop % compute}"
    calls = "".join(
        f"    result = result + {callee[i]}(values, scale)\n" for i in range(wrapped)
    )
    return (
        out
        + f"def run_all(values, scale):\n    result = []\n{calls}    return result\n"
    )


GOOD = "".join(
    f"def total_price_{i}(prices, discount):\n    subtotal = 0\n"
    + "".join(
        f"    for price in prices:\n        if price > {j}:\n"
        f"            subtotal = subtotal + price * discount + {j}\n"
        for j in range(5)
    )
    + "    return subtotal\n\n\n"
    for i in range(3)
)
# Flip lines sit at fixed offsets above the before-score, never at the real score.
FLIP_OFFSETS = (0.5, 2.0, 5.0)
SPLIT_SIZES = (14, 18, 22, 28, 34, 40, 50)
WRAPPER_SHAPES = ((4, 3), (4, 4), (5, 5), (6, 4), (8, 6), (6, 6), (3, 3), (8, 8))


def _first(fixes, measures):
    return next(f for f in fixes if f["measure"] in measures and not f["advisory"])


def _flips_agree(before: float, predicted: float, real: float) -> bool:
    """Prediction and real edit cross every fixed line alike, outside the tolerance."""
    lines = [before + offset for offset in FLIP_OFFSETS]
    return all(
        (predicted >= line) == (real >= line)
        for line in lines
        if abs(real - line) > TOLERANCE
    )


def test_fields_ranking_and_cap() -> None:
    record = _facts(_long(30))
    fixes = fix_explain.fixes(record, CAL, 99.0, top=2)
    assert len(fixes) <= 2
    assert all(set(fix) == FIELDS for fix in fixes)
    assert [fix["rank"] for fix in fixes] == [1, 2][: len(fixes)]
    scored = [f for f in fixes if not f["advisory"]]
    gains = [f["predicted_score"] for f in scored]
    assert gains == sorted(gains, reverse=True)
    assert fixes[0]["advisory"] is False
    assert fixes[0]["distance_to_line"] > 0


def test_advisory_entries_follow_scored_ones() -> None:
    fixes = fix_explain.fixes(_facts(_long(30)), CAL, 99.0, top=10)
    flags = [fix["advisory"] for fix in fixes]
    assert flags == sorted(flags)
    for fix in fixes:
        assert (fix["predicted_score"] is None) == fix["advisory"]
        assert ("advisory, does not change score" in fix["change"]) == fix["advisory"]


def test_nesting_only_fixture_is_advisory() -> None:
    source = (
        "def pick(rows, limit):\n    found = []\n    for row in rows:\n"
        "        if row:\n            if row > limit:\n"
        "                found.append(row)\n"
        "    return found\n"
    )
    fixes = fix_explain.fixes(_facts(source), CAL, 100.0)
    nesting = [f for f in fixes if f["measure"] == "nesting"]
    assert nesting
    assert all(f["advisory"] and f["predicted_score"] is None for f in nesting)


def test_non_scored_language_keeps_split_and_nesting_advisories() -> None:
    function = {"id": "m.ts::a#1", "tokens": 500, "cognitive": 40, "max_nesting": 4}
    record = {"path": "m.ts", "language": "typescript", "functions": [function]}
    found = fix_explain._candidates(record, {"Phi": 96, "c0": 10, "n0": 1})
    assert [(measure, edit) for _, measure, edit in found] == [
        ("long_side", None),
        ("nesting", None),
    ]


def test_typescript_is_advisory_only() -> None:
    source = "export function a(x: number) {\n" + "  if (x > 1) { x = x + 1; }\n" * 60
    source += "  return x;\n}\n"
    record = _facts(source, "m.ts", "typescript")
    fixes = fix_explain.fixes(record, CAL, 100.0)
    assert all(f["advisory"] and f["predicted_score"] is None for f in fixes)


def test_file_at_or_above_line_has_no_fixes() -> None:
    record = _facts(_long(30))
    score = _score(record)
    assert fix_explain.fixes(record, CAL, score) == []
    assert fix_explain.fixes(record, CAL, 0.0) == []


def test_oracle_split() -> None:
    mismatches, flips = [], 0
    for size in SPLIT_SIZES:
        before = _facts(_long(size))
        score = _score(before)
        predicted = _first(
            fix_explain.fixes(before, CAL, 100.0), {"long_side", "cognitive"}
        )
        real = _score(_facts(_split(size)))
        if abs(predicted["predicted_score"] - real) > TOLERANCE:
            mismatches.append((size, predicted["predicted_score"], real))
        flips += _flips_agree(score, predicted["predicted_score"], real)
    assert not mismatches, (
        f"{len(mismatches)}/{len(SPLIT_SIZES)} split mismatches: {mismatches}"
    )
    assert flips == len(SPLIT_SIZES)


def test_oracle_drop_wrapper() -> None:
    mismatches = []
    for compute, wrapped in WRAPPER_SHAPES:
        before = _facts(_wrappers(compute, wrapped, None))
        score = _score(before)
        predicted = _first(fix_explain.fixes(before, CAL, 100.0), {"delegation"})
        dropped = int(predicted["function"].removeprefix("wrap_"))
        real = _score(_facts(_wrappers(compute, wrapped, dropped)))
        if abs(predicted["predicted_score"] - real) > TOLERANCE:
            mismatches.append((compute, wrapped, predicted["predicted_score"], real))
        assert _flips_agree(score, predicted["predicted_score"], real)
    assert not mismatches, (
        f"{len(mismatches)}/{len(WRAPPER_SHAPES)} wrapper mismatches: {mismatches}"
    )


HOOKS = {
    "decorated": "@property\ndef hooked(self):\n    return compute_0(self)\n",
    "dunder": "def __enter__(self):\n    return compute_0(self)\n",
    "main": "def main():\n    return compute_0(1)\n",
    "super": "def hooked(self):\n    return super().hooked()\n",
    "override": (
        "class Sub(Base):\n    def hooked(self):\n        return compute_0(self)\n"
    ),
}


def _delegating(hook: str | None) -> str:
    source = _wrappers(6, 6, None)
    return source if hook is None else source + "\n\n" + HOOKS[hook]


def test_hook_flag_marks_contract_functions() -> None:
    for name, snippet in HOOKS.items():
        record = _facts(snippet)
        assert all(f["hook"] for f in record["functions"]), name
    plain = _facts("def wrap(a):\n    return compute(a)\n")
    assert [f["hook"] for f in plain["functions"]] == [False]
    base = _facts("class Plain:\n    def wrap(self):\n        return compute(self)\n")
    assert [f["hook"] for f in base["functions"]] == [False]


@pytest.mark.parametrize("hook", sorted(HOOKS))
def test_hook_wrappers_are_not_offered(hook: str) -> None:
    record = _facts(_delegating(hook))
    hooked = {f["id"] for f in record["functions"] if f["hook"]}
    assert hooked
    offered = fix_explain.fixes(record, CAL, 100.0, top=50)
    names = {f["function"] for f in offered if f["measure"] == "delegation"}
    assert names
    assert "hooked" not in names and "main" not in names


def test_wrapper_fix_needs_the_minimum_gain(monkeypatch: pytest.MonkeyPatch) -> None:
    record = _facts(_wrappers(6, 6, None))
    offered = fix_explain.fixes(record, CAL, 100.0, top=50)
    wrappers = [f for f in offered if f["measure"] == "delegation"]
    assert wrappers
    assert all(
        f["predicted_score"] - _score(record) >= fix_explain.MIN_WRAPPER_GAIN - 0.05
        for f in wrappers
    )
    monkeypatch.setattr(fix_explain, "MIN_WRAPPER_GAIN", 100.0)
    none = fix_explain.fixes(record, CAL, 100.0, top=50)
    assert not [f for f in none if f["measure"] == "delegation"]


def test_module_reads_no_labels() -> None:
    tree = ast.parse(Path(fix_explain.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not any("baseline" in name or "overlay" in name for name in imported)


class _IO:
    def __init__(self) -> None:
        self.stdout = StringIO()
        self.stderr = StringIO()


def _score_file(tmp_path: Path, source: str, *options: str) -> tuple[int, str]:
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
    (tmp_path / "bad.py").write_text(source, encoding="utf-8")
    io = _IO()
    code = run(["score", "--file", str(tmp_path / "bad.py"), *options], io)
    return code, io.stdout.getvalue()


def test_cli_json_adds_fixes_only(tmp_path) -> None:
    code, out = _score_file(tmp_path, _long(30), "--vs", "generic", "--json")
    assert code == 0
    view = json.loads(out)
    assert view["refactor"]["needs_refactor"] is True
    assert view["fixes"]
    assert set(view["fixes"][0]) == FIELDS


def test_cli_text_lists_fixes_below_the_line(tmp_path) -> None:
    code, out = _score_file(tmp_path, _long(30), "--vs", "generic")
    assert code == 0
    assert "What to change, in order:" in out
    assert "bad.py:" in out


def test_cli_good_file_has_no_fix_list(tmp_path) -> None:
    code, out = _score_file(tmp_path, GOOD, "--vs", "generic")
    assert code == 0
    assert "What to change" not in out
    assert "refactor" not in out.lower().replace("worth refactoring", "")


@pytest.mark.parametrize("flag", [[], ["--json"]])
def test_no_vs_leaves_view_unchanged(tmp_path, flag) -> None:
    code, out = _score_file(tmp_path, _long(30), *flag)
    assert code == 0
    assert "What to change" not in out
    assert "fixes" not in out


def test_cli_vs_repo_defaults_reference_to_auto(tmp_path) -> None:
    import subprocess

    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
    (tmp_path / "bad.py").write_text(_long(30), encoding="utf-8")
    subprocess.run([*git, "add", "."], check=True)  # noqa: S603
    subprocess.run([*git, "commit", "-qm", "x"], check=True)  # noqa: S603
    io = _IO()
    args = ["score", "--file", str(tmp_path / "bad.py"), "--vs", "repo", "--json"]
    assert run(args, io) == 0
    assert json.loads(io.stdout.getvalue())["refactor"]["vs"] == "repo"


def test_cli_vs_generic_needs_no_reference(tmp_path) -> None:
    code, out = _score_file(tmp_path, _long(30), "--vs", "generic", "--json")
    assert code == 0
    assert json.loads(out)["refactor"]["vs"] == "generic"


def test_advisory_entries_are_capped_and_ranked_by_loss() -> None:
    source = "".join(
        f"def f{i}(rows):\n    for r in rows:\n        if r:\n            if r > {i}:\n"
        "                return r\n\n\n"
        for i in range(6)
    )
    fixes = fix_explain.fixes(_facts(source), CAL, 100.0, top=10)
    advisory = [f for f in fixes if f["advisory"]]
    assert len(advisory) <= fix_explain.ADVISORY_CAP
    losses = [f["contribution_points"] for f in advisory]
    assert losses == sorted(losses, reverse=True)


def test_note_explains_a_flagged_file_with_no_fix() -> None:
    record = _facts("def clamp(value):\n    return value\n")
    note = fix_explain.no_scored_fix_note(record, CAL, [])
    assert note.startswith("no ")
    advisory = [{"advisory": True}]
    assert "advisory only" in fix_explain.no_scored_fix_note(record, CAL, advisory)
    assert fix_explain.no_scored_fix_note(record, CAL, [{"advisory": False}]) == ""
