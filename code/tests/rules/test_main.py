import json
import sqlite3
from pathlib import Path

from varde_code.model import Entity, EntityKind, ExtractOutput, Span
from varde_code.rules.__main__ import (
    ExtractionJsonProvider,
    response_envelope,
    response_exit_code,
    scan,
)
from varde_code.rules.model import Rule, RuleKind, Severity


class FakeProvider:
    def extract(self, path, source, language):
        return ExtractOutput(
            entities=[Entity(EntityKind.IMPORT, "thing", 1, Span(0, 5, 1, 0, 1, 5))]
        )


def test_response_envelope_matches_scan_cli_contract():
    payload = {
        "outcome": "code-quality-error",
        "outcome_reasons": ["code-quality-error"],
    }

    assert response_envelope(payload) == {
        "data": payload,
        "meta": {"compact": True, "truncated": False},
        "ok": True,
        "outcome": "code-quality-error",
        "schema_version": 1,
    }
    assert response_exit_code({"gate": {"status": "pass"}}) == 0
    assert response_exit_code({"gate": {"status": "fail"}}) == 1
    assert response_exit_code({"gate": {"status": "unknown"}}) == 1


def test_scan_serializes_findings_and_accepts_provider_seam(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("import thing\n", encoding="utf-8")
    db = sqlite3.connect(":memory:")
    db.execute(
        (  # noqa: UP034 - grouping keeps adjacent SQL literals clear
            "CREATE TABLE files (id INTEGER, path TEXT, is_test_path INTEGER, "
            "is_tooling_path INTEGER)"
        )
    )
    db.execute(
        (  # noqa: UP034 - grouping keeps adjacent SQL literals clear
            "CREATE TABLE entities (file_id INTEGER, kind INTEGER, name TEXT, "
            "is_async INTEGER, start_byte INTEGER, end_byte INTEGER)"
        )
    )
    db.execute("CREATE TABLE t (file TEXT, line INTEGER)")
    db.execute("INSERT INTO t VALUES ('source.py', 1)")
    rule = Rule(
        "r", RuleKind.SQL, Severity.ERROR, "found", query="SELECT file, line FROM t"
    )

    payload = scan(tmp_path, db, [rule], FakeProvider(), rule_diagnostics=[])

    assert list(payload) == [
        "analysis",
        "diagnostics",
        "findings",
        "findings_summary",
        "gate",
        "outcome",
        "outcome_reasons",
        "policy",
        "rules",
    ]
    assert payload["findings"][0]["id"]
    assert list(payload["findings"][0]) == sorted(payload["findings"][0])
    assert "message" not in payload["findings"][0]
    assert payload["rules"]["r"] == {"message": "found"}
    assert payload["findings_summary"] == {
        "total": 1,
        "shown": 1,
        "truncated": False,
        "by_rule": {"r": 1},
        "by_severity": {"error": 1, "info": 0, "warning": 0},
        "offset": 0,
    }
    assert payload["gate"]["blocking_findings"] == 1
    assert payload["analysis"] == {"status": "complete"}
    db.close()


def test_extraction_json_provider_reads_json_result(tmp_path: Path) -> None:
    fixture = tmp_path / "extract.json"
    fixture.write_text(
        json.dumps(
            {
                "data": {
                    "entities": [
                        {
                            "kind": "import",
                            "name": "thing",
                            "file_id": 0,
                            "span": {
                                "start_byte": 0,
                                "end_byte": 5,
                                "start_line": 1,
                                "start_col": 0,
                                "end_line": 1,
                                "end_col": 5,
                            },
                        }
                    ],
                    "files": ["source.py"],
                }
            }
        ),
        encoding="utf-8",
    )

    output = ExtractionJsonProvider(fixture, tmp_path).extract(
        tmp_path / "source.py", "import thing", "python"
    )

    assert output.entities[0].name == "thing"
    assert output.entities[0].kind is EntityKind.IMPORT
