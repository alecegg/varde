from __future__ import annotations

import sqlite3

import pytest
from varde_code import ApiError
from varde_code.model import Span
from varde_code.rules import clone_verification
from varde_code.rules.clone_verification import verify
from varde_code.rules.correlate import EnclosingLookup, TestPathLookup
from varde_code.rules.finding import (
    FileState,
    Finding,
    Location,
    finding_id,
    match_to_finding,
    resolve_real_path,
)
from varde_code.rules.model import Diagnostic, Rule, Severity
from varde_code.rules.scan_output import build_scan_payload
from varde_code.rules.suppress import filter_findings, parse_suppressions


def rule(**overrides: object) -> Rule:
    values = {
        "id": "rule",
        "kind": "pattern",
        "severity": "warning",
        "message": "found",
        **overrides,
    }
    return Rule.from_mapping(values)


def finding(file: str, start: int, end: int, line: int = 1) -> Finding:
    span = Span(start, end, line, 0, line, 10)
    return Finding(
        finding_id("rule", file, span),
        "rule",
        Severity.WARNING,
        "found",
        Location(file, span),
        {},
        None,
    )


def test_finding_id_matches_rust_field_separator_hash() -> None:
    span = Span(4, 9, 1, 4, 1, 9)
    assert finding_id("rule", "src/a.py", span) == "f348ce5e093fa367"
    assert finding_id("ab", "c", span) != finding_id("a", "bc", span)


def test_match_finding_and_json_field_order_match_rust_shape() -> None:
    item = match_to_finding(
        rule(remediation="fix", fix="inspect"),
        {
            "captures": {
                "NAME": {
                    "text": "x",
                    "span": {
                        "start_byte": 0,
                        "end_byte": 1,
                        "start_line": 1,
                        "start_col": 0,
                        "end_line": 1,
                        "end_col": 1,
                    },
                }
            }
        },
        Location("a.py", Span(0, 1, 1, 0, 1, 1)),
    )
    assert item.certainty == "high"
    assert item.evidence["NAME"]["text"] == "x"
    assert list(item.to_dict()) == [
        "id",
        "rule_id",
        "severity",
        "message",
        "location",
        "evidence",
        "remediation",
        "certainty",
        "agent_instructions",
    ]
    assert item.to_dict()["location"]["span"] == {
        "start_line": 1,
        "end_line": 1,
    }
    assert item.to_dict()["evidence"]["NAME"]["span"] == {
        "start_line": 1,
        "end_line": 1,
    }
    sql_like = finding("a.py", 0, 1).to_dict()
    assert list(sql_like) == [
        "id",
        "rule_id",
        "severity",
        "message",
        "location",
        "evidence",
        "remediation",
    ]


def test_finding_path_is_hashed_before_display_path_is_made_relative(tmp_path):
    source = tmp_path / "src" / "a.py"
    span = Span(4, 9, 2, 0, 2, 5)
    pattern_item = match_to_finding(rule(), {}, Location(str(source), span))
    sql_item = finding(str(source), 4, 9, 2)
    expected_pattern_id = finding_id("rule", str(source), span)
    expected_sql_id = finding_id("rule", str(source), sql_item.location.span)

    payload = build_scan_payload([pattern_item, sql_item], [], [], [], tmp_path)

    assert [item["location"]["file"] for item in payload["findings"]] == [
        "src/a.py",
        "src/a.py",
    ]
    assert [item["id"] for item in payload["findings"]] == [
        expected_pattern_id,
        expected_sql_id,
    ]


def test_file_state_and_real_path_are_best_effort(tmp_path) -> None:
    source = tmp_path / "source.py"
    source.write_text("pass\n", encoding="utf-8")
    alias = tmp_path / "alias.py"
    alias.symlink_to(source)
    state = FileState.of(source)
    assert state is not None and state.length == 5
    assert FileState.of(tmp_path / "missing.py") is None
    assert resolve_real_path(alias) == source.resolve()


def test_suppression_parses_scoped_ids_reason_and_ignores_strings() -> None:
    source = (
        'value = "varde-ignore-file"\n# varde-ignore-next-line one, two -- '
        "reason\nalert()\n"
    )
    result = parse_suppressions(source, "a.py")
    assert result == [type(result[0])(3, 2, ["one", "two"], "reason")]
    assert parse_suppressions('x = "varde-ignore-file"\n', "a.py") == []
    assert parse_suppressions("# å varde-ignore-file\n", "a.py")[0].line == 0
    assert parse_suppressions("// varde-ignore-file\n", "unsupported.unknown") == []


def test_filter_suppresses_and_reports_unused_directive_preserving_input_order(
    tmp_path,
) -> None:
    (tmp_path / "a.py").write_text(
        (
            "# varde-ignore-next-line other\nfirst()\n"
            "# varde-ignore-next-line rule -- reason\nlast()\n"
        ),
        encoding="utf-8",
    )
    first = finding("a.py", 10, 15, 2)
    second = finding("a.py", 30, 34, 4)
    other_file = finding("b.py", 1, 2, 1)
    kept, stale = filter_findings([first, other_file, second], tmp_path)
    assert kept == [first, other_file]
    assert [(item.comment_line, item.rule_ids, item.reason) for item in stale] == [
        (1, ["other"], None)
    ]


def test_filter_resolves_cwd_relative_repo_paths_before_joining_root(
    tmp_path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text(
        "# varde-ignore-next-line rule\nfound()\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    kept, stale = filter_findings([finding("repo/a.py", 25, 30, 2)], repo)

    assert kept == []
    assert stale == []


def test_file_wide_suppression_drops_findings_from_every_line(tmp_path) -> None:
    (tmp_path / "a.py").write_text(
        "# varde-ignore-file\nfirst()\nlast()\n", encoding="utf-8"
    )
    kept, stale = filter_findings([finding("a.py", 20, 24, 3)], tmp_path)
    assert kept == []
    assert stale == []


def test_enclosing_lookup_returns_narrowest_and_maps_errors() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
      CREATE TABLE files(id INTEGER PRIMARY KEY, path TEXT, is_test_path INTEGER, \
is_tooling_path INTEGER);
      CREATE TABLE entities(kind INTEGER, name TEXT, file_id INTEGER, \
start_byte INTEGER, end_byte INTEGER, is_async INTEGER);
      INSERT INTO files VALUES(1, 'a.py', 1, 0);
      INSERT INTO entities VALUES(0, 'outer', 1, 0, 100, 1);
      INSERT INTO entities VALUES(0, 'inner', 1, 20, 40, 0);
    """)
    lookup = EnclosingLookup(conn)
    fact = lookup.lookup("a.py", 25, 30)
    assert fact is not None
    assert fact.name == "inner"
    assert fact.is_async is False
    assert lookup.lookup("a.py", 200, 210) is None
    conn.execute("DROP TABLE entities")
    with pytest.raises(ApiError) as error:
        lookup.lookup("a.py", 1, 2)
    assert error.value.code == "db_error"


def test_test_path_lookup_caches_flags_and_defaults_absent_rows() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE files(path TEXT, is_test_path INTEGER, is_tooling_path INTEGER)"
    )
    conn.execute("INSERT INTO files VALUES ('a.py', 1, 0)")
    lookup = TestPathLookup(conn)
    assert (lookup.is_test_path("a.py"), lookup.is_tooling_path("a.py")) == (
        True,
        False,
    )
    assert (
        lookup.is_test_path("missing.py"),
        lookup.is_tooling_path("missing.py"),
    ) == (False, False)
    conn.close()
    # Cached paths remain available after the backing connection is closed.
    assert lookup.is_test_path("a.py") is True


def test_clone_verification_groups_deduplicates_and_orders_members(tmp_path) -> None:
    source = "def same():\n    return 1 + 2\n"
    candidates = []
    for name in ("c.py", "a.py", "b.py", "b.py"):
        path = tmp_path / name
        path.write_text(source, encoding="utf-8")
        span = Span(0, len(source.encode()), 1, 0, 3, 0)
        candidates.append(
            Finding(
                f"id-{name}",
                "clone",
                Severity.WARNING,
                "clone",
                Location(str(path), span),
                {},
                None,
            )
        )
    clone_rule = rule(
        id="clone", thresholds={"min_tokens": 1, "min_members": 3, "min_span_lines": 0}
    )
    output, diagnostics = verify(clone_rule, tmp_path, candidates)
    assert diagnostics == []
    assert [item.location.file for item in output] == [
        str(tmp_path / name) for name in ("a.py", "b.py", "c.py")
    ]
    assert all(item.evidence["verification"] == "exact-clone" for item in output)
    assert all(
        item.evidence["members"][0]["file"] == str(tmp_path / "a.py") for item in output
    )
    assert all(
        item.id == finding_id(item.rule_id, item.location.file, item.location.span)
        for item in output
    )


def test_clone_thresholds_validated_even_without_candidates() -> None:
    invalid = rule(id="clone", thresholds={"min_tokens": 0})
    findings, diagnostics = verify(invalid, ".", [])
    assert findings == []
    assert diagnostics == [
        Diagnostic(
            "clone", "", "min_tokens must be an integer between 1 and 4294967295"
        )
    ]


def test_clone_verification_reports_rust_utf8_read_error(tmp_path) -> None:
    source = tmp_path / "clone.py"
    source.write_bytes(b"def same():\n    return \xff\n")
    candidate = Finding(
        "candidate",
        "clone",
        Severity.WARNING,
        "clone",
        Location(str(source), Span(0, 1, 1, 0, 1, 1)),
        {},
        None,
    )

    output, diagnostics = verify(rule(id="clone"), tmp_path, [candidate])

    assert output == []
    assert diagnostics == [
        Diagnostic(
            "clone",
            str(source),
            "source read failed: stream did not contain valid UTF-8",
        )
    ]


def test_clone_verification_handles_unmapped_language_without_crashing(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "clone.py"
    source.write_text("def same():\n    return 1\n", encoding="utf-8")
    candidate = Finding(
        "candidate",
        "clone",
        Severity.WARNING,
        "clone",
        Location(str(source), Span(0, 25, 1, 0, 3, 0)),
        {},
        None,
    )
    monkeypatch.delitem(clone_verification.RUST_LANG_NAMES, "python")

    output, diagnostics = verify(rule(id="clone"), tmp_path, [candidate])

    assert output == []
    assert diagnostics == [Diagnostic("clone", str(source), "unsupported clone source")]
