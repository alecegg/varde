from __future__ import annotations

import io
import json
from pathlib import Path
from typing import cast

import pytest
from varde_learn.docs.pages.blocks.fences import find_fences
from varde_learn.docs.pages.blocks.lines_check import check_lines
from varde_learn.docs.pages.lines import parse_lines
from varde_learn.loop import cli_skills_report
from varde_learn.loop.improve import record as rec
from varde_learn.loop.improve.record import LoopRecord
from varde_learn.loop.improve.report_page import build_page

FIXTURES = Path(__file__).parents[1] / "fixtures" / "improve-report"
NASTY_DIFF = '--- a\n+++ b\n-"quoted" \\ back```\n+<script>alert(1)</script>\n'


def fixture_records() -> list[tuple[LoopRecord, str]]:
    rows = json.loads((FIXTURES / "records.json").read_text())
    return [
        (
            LoopRecord(**{**r, "trigger": tuple(r["trigger"])}),
            r.get("_diff", NASTY_DIFF),
        )
        for r in rows
    ]


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


@pytest.fixture
def store_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("VARDE_MEMORY_DIR", str(tmp_path / "mem"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.chdir(tmp_path)
    for record, diff in fixture_records():
        rec.write_record(tmp_path / "mem", record, diff)
    return tmp_path / "mem"


def test_one_decision_block_per_open_proposal_with_evidence() -> None:
    pairs = [(r, d) for r, d in fixture_records() if r.state == "proposed"]
    page = build_page("2026-11-01", pairs)
    fences = find_fences(page, frozenset({"ui"}))
    assert [f.id_text for f in fences] == [r.id for r, _ in pairs]
    for fence, (record, diff) in zip(fences, pairs, strict=True):
        assert check_lines(fence.body) == []
        (statement,) = parse_lines(fence.body).statements
        assert statement.id == record.id and statement.component == "decision"
        data = statement.props
        assert data["diff"] == diff
        labels = {row["label"]: row["text"] for row in cast("list", data["evidence"])}
        assert labels["token delta"] == f"{record.token_delta:+d} tokens per run"
        assert labels["friction"] == ", ".join(record.trigger) or "none recorded"
        assert labels["later demand"] != ""
        assert labels["change"] == record.change


def test_text_is_escaped() -> None:
    page = build_page("2026-11-01", fixture_records()[:1])
    assert "<script>" not in page.split("```ui", 1)[0]
    assert "\n+<script>" not in page


def test_report_json_lists_every_record_and_writes_page(store_dir: Path) -> None:
    out = Io()
    assert cli_skills_report.run(["--json"], out) == 0
    data = json.loads(out.stdout.getvalue())["data"]
    assert {r["id"] for r in data["records"]} == {r.id for r, _ in fixture_records()}
    page = Path(data["page"])
    assert page.parent == store_dir / "loop" / "report"
    assert page.read_text().count("```ui id=") == 2


def test_no_page_without_open_proposals(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VARDE_MEMORY_DIR", str(tmp_path / "mem"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.chdir(tmp_path)
    out = Io()
    assert cli_skills_report.run(["--json"], out) == 0
    assert json.loads(out.stdout.getvalue())["data"] == {"records": [], "page": None}
