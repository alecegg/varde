"""`learn docs comments --kind decision` and the decision line of `watch`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from varde_learn.docs import cli
from varde_learn.docs.pages.comments import append_comment, append_reply
from varde_learn.docs.pages.watch import watch_lines


def decide(doc: Path, item: str, verdict: str, text: str = "") -> dict:
    extra = {"kind": "decision", "item": item, "verdict": verdict}
    return append_comment(doc, item, "", text or f"{verdict}: {item}", extra=extra)


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    path = tmp_path / "plan.md"
    path.write_text("# Plan\n", encoding="utf-8")
    return path


def test_kind_decision_json_marks_latest_per_block(doc, capsys):
    decide(doc, "a", "approved")
    decide(doc, "a", "denied")
    decide(doc, "b", "commented", "later please")
    append_comment(doc, "intro", "", "plain remark")
    assert cli.run(["comments", str(doc), "--kind", "decision", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["data"]["comments"]
    assert [(r["item"], r["verdict"], r["latest"]) for r in rows] == [
        ("a", "approved", False),
        ("a", "denied", True),
        ("b", "commented", True),
    ]
    assert all(r["ts"] and r["kind"] == "decision" for r in rows)
    assert rows[2]["text"] == "later please"


def test_kind_decision_text_lists_block_verdict_and_latest(doc, capsys):
    decide(doc, "a", "approved")
    decide(doc, "a", "denied")
    assert cli.run(["comments", str(doc), "--kind", "decision"]) == 0
    heads = [
        line for line in capsys.readouterr().out.splitlines() if " decision " in line
    ]
    assert " a approved " in heads[0] and "latest" not in heads[0]
    assert " a denied latest " in heads[1]


def test_without_kind_other_rows_remain(doc, capsys):
    decide(doc, "a", "approved")
    append_comment(doc, "intro", "", "plain remark")
    assert cli.run(["comments", str(doc), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["data"]["comments"]
    assert [r["kind"] for r in rows] == ["decision", "comment"]


def test_bad_kind_is_a_usage_error(doc, capsys):
    assert cli.run(["comments", str(doc), "--kind", "nope"]) != 0
    assert "--kind" in capsys.readouterr().err


def test_comments_help_names_kind(capsys):
    assert cli.run(["comments", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--kind" in out and len(out.splitlines()) < 40


def test_watch_prints_decision_line_and_skips_resolved(doc):
    lines = watch_lines(doc, "1s", include_backlog=True, sleep=lambda _s: None)
    row = decide(doc, "ship", "denied", "too risky")
    assert next(lines) == f"decision {row['id']} ship denied too risky"
    other = decide(doc, "ship", "approved")
    append_reply(doc, other["id"], "noted")
    plain = append_comment(doc, "intro", "", "remark")
    assert next(lines).startswith(f"comment {plain['id']} intro")
