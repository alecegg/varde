"""Pin: the runtime scorer reads cal-1's ``dominance`` (2.00) via ``varde score``."""

import json
from io import StringIO
from pathlib import Path

from varde_code.quality_score.cli import run

CAL1 = Path(__file__).parents[3] / "src/varde_code/quality_score/calibration/cal-1.toml"
DOMINANCE_LINE = 'dominance = "2.00"'


def _monolith_facts(path: Path) -> None:
    function = {
        "id": "src/m.py::big",
        "name": "big",
        "line": 3,
        "tokens": 900,
        "cognitive": 30,
        "params": 1,
        "depth": 1,
        "fan_out": 1,
        "tree_size": 1,
        "name_issues": [],
        "fragment_scope": None,
    }
    record = {
        "contract": "facts-2",
        "path": "src/m.py",
        "language": "python",
        "module": "src",
        "tokens": 1000,
        "structure_confidence": "normal",
        "functions": [function],
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


def _score(facts: Path, calibration: Path) -> float:
    out = StringIO()

    class _IO:
        stdout = out
        stderr = StringIO()

    code = run(
        ["score", "--facts", str(facts), "--calibration", str(calibration), "--json"],
        _IO,
    )
    assert code == 0
    return json.loads(out.getvalue())["score"]


def test_cal1_dominance_changes_the_monolith_score_through_the_cli(tmp_path):
    text = CAL1.read_text(encoding="utf-8")
    assert DOMINANCE_LINE in text
    zero = tmp_path / "cal-1-zero.toml"
    zero.write_text(
        text.replace(DOMINANCE_LINE, 'dominance = "0.00"'), encoding="utf-8"
    )
    facts = tmp_path / "facts.jsonl"
    _monolith_facts(facts)
    assert _score(facts, CAL1) != _score(facts, zero)
