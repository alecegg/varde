"""Python counterparts for flow ledger and rendering behavior."""

import hashlib
import json
from pathlib import Path

from varde_learn.docs.flow.analyze import DIAGRAM_EDGES_MEASURE, analyze_skill
from varde_learn.docs.flow.ledger import check, hash_ledger, score, validate
from varde_learn.docs.flow.render import flow_doc, mermaid, text_report


def test_hash_action_writes_the_cited_line_hash(tmp_path: Path):
    from varde_learn.docs.cli import run

    (tmp_path / "source.md").write_text("one\ntwo\n", encoding="utf-8")
    ledger = tmp_path / "ledger.json"
    ledger.write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "id": "D1",
                        "phase": "build",
                        "source": "source.md",
                        "line_start": 1,
                        "line_end": 2,
                        "alternatives": ["a", "b"],
                        "units": 1,
                        "depth": 0,
                    }
                ],
                "files": [{"path": "source.md"}],
            }
        )
    )

    assert run(["flow", "ledger", "hash", str(ledger), "--root", str(tmp_path)]) == 0
    recorded = json.loads(ledger.read_text(encoding="utf-8"))
    assert recorded["decisions"][0]["hash"] == hashlib.sha256(b"one\ntwo").hexdigest()


def test_cited_lines_split_on_universal_line_boundaries(tmp_path: Path):
    (tmp_path / "source.md").write_bytes("one\r\ntwo\rthree\u2028four\n".encode())
    lines = ["one", "two", "three", "four"]
    data = {
        "decisions": [
            {
                "id": "D1",
                "phase": "build",
                "source": "source.md",
                "line_start": 1,
                "line_end": 4,
                "alternatives": ["a", "b"],
                "units": 1,
                "depth": 0,
                "hash": hashlib.sha256("\n".join(lines).encode()).hexdigest(),
            }
        ],
        "files": [{"path": "source.md"}],
    }
    assert validate(data, tmp_path) == []


def test_unresolved_calls_render_sorted_ascii_json(tmp_path: Path):
    data = {
        "decisions": [],
        "files": [],
        "unresolved_calls": [{"kind": "local", "target": "caf\u00e9"}],
    }
    assert validate(data, tmp_path) == [
        'unresolved local call: {"kind": "local", "target": "caf\\u00e9"}'
    ]


def test_ledger_score_validate_check_and_hash(tmp_path: Path):
    (tmp_path / "source.md").write_text("one\ntwo\n", encoding="utf-8")
    data = {
        "decisions": [
            {
                "id": "D1",
                "phase": "build",
                "source": "source.md",
                "line_start": 1,
                "line_end": 1,
                "alternatives": ["a", "b"],
                "units": 1,
                "depth": 0,
            }
        ],
        "files": [{"path": "source.md"}],
        "routes": {"build": ["build"]},
    }
    assert score(data) == {
        "decisions": 1,
        "branch_units": 1,
        "cyclomatic": 2,
        "cognitive": 1,
        "phases": {"build": {"decisions": 1, "branch_units": 1, "cognitive": 1}},
    }
    assert score(data, "build")["decisions"] == 1
    assert validate(data, tmp_path) == ["D1: hash does not match cited lines"]
    assert hash_ledger(data, tmp_path) == 1
    assert validate(data, tmp_path) == []
    (tmp_path / "source.md").write_text("intro\none\ntwo\n", encoding="utf-8")
    assert check(data, tmp_path) == ["D1: moved to source.md lines 2-2"]


def test_render_outputs_reports_mermaid_and_flow_doc(tmp_path: Path):
    skill = tmp_path / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "| Route | Read |\n|---|---|\n| Build | `references/build.md` |\n",
        encoding="utf-8",
    )
    (skill / "references").mkdir()
    (skill / "references/build.md").write_text("Build step\n", encoding="utf-8")
    data = analyze_skill(skill)
    assert text_report(data).startswith("== demo (SKILL.md ~")
    assert mermaid(data).startswith("%% demo\nflowchart TD\n")
    rendered = flow_doc(data)
    assert rendered.startswith("# demo flow\n")
    assert "## Routes\n" in rendered and rendered.endswith("\n")
    assert "```mermaid" not in rendered
    assert DIAGRAM_EDGES_MEASURE not in rendered
    assert DIAGRAM_EDGES_MEASURE in text_report(data)
