from varde_design.ignores import (
    MIN_REASON_CHARS,
    apply_ignores,
    parse_ignores,
)
from varde_design.report import Finding, build_report, checked_block, validate_report

REASON = "brand colour approved by design"


def finding(rule: str, line: int, severity: str = "warn", file: str = "a.css"):
    return Finding(rule, severity, "static", file, "m", line=line)


def test_parses_ids_and_reason_in_css_and_html_comments() -> None:
    css = f"/* design-ignore S7, s9 reason: {REASON} */\n"
    html = f"<!-- design-ignore S7 reason: {REASON} -->\n"
    ig_css, bad_css = parse_ignores(css, "a.css")
    ig_html, bad_html = parse_ignores(html, "a.html")
    assert not bad_css and not bad_html
    assert ig_css[0].ids == ("S7", "S9")
    assert ig_css[0].reason == REASON and ig_css[0].line == 1
    assert ig_html[0].reason == REASON


def test_reason_runs_to_line_end_without_comment_closer() -> None:
    ignores, bad = parse_ignores(f"// design-ignore S4 reason: {REASON}\n", "a.js")
    assert not bad and ignores[0].reason == REASON


def test_short_reason_is_a_finding_and_waives_nothing() -> None:
    ignores, bad = parse_ignores("/* design-ignore S7 reason: too short */", "a.css")
    assert ignores == []
    assert [f.id for f in bad] == ["IGN"]
    assert str(MIN_REASON_CHARS) in bad[0].message
    kept, echoes = apply_ignores([finding("S7", 1)], ignores)
    assert len(kept) == 1 and echoes == []


def test_reason_of_exactly_the_minimum_is_accepted() -> None:
    reason = "x" * MIN_REASON_CHARS
    ignores, bad = parse_ignores(f"/* design-ignore S7 reason: {reason} */", "a.css")
    assert len(ignores) == 1 and not bad
    ignores, bad = parse_ignores(
        f"/* design-ignore S7 reason: {reason[:-1]} */", "a.css"
    )
    assert not ignores and len(bad) == 1


def test_malformed_comments_are_findings() -> None:
    cases = [
        "/* design-ignore */",
        "/* design-ignore S7 */",
        f"/* design-ignore reason: {REASON} */",
        f"/* design-ignore S7,, reason: {REASON} */",
        f"/* design-ignore seven reason: {REASON} */",
        f"/* design-ignore S99 reason: {REASON} */",
    ]
    for text in cases:
        ignores, bad = parse_ignores(text, "a.css")
        assert ignores == [] and [f.id for f in bad] == ["IGN"], text


def test_text_without_marker_yields_nothing() -> None:
    assert parse_ignores("a { color: red }\n/* note */\n", "a.css") == ([], [])
    assert parse_ignores("", "a.css") == ([], [])


def test_applies_to_same_line_and_next_line_only() -> None:
    ignores, _ = parse_ignores(f"/* design-ignore S7 reason: {REASON} */", "a.css")
    found = [finding("S7", 1), finding("S7", 2), finding("S7", 3)]
    kept, echoes = apply_ignores(found, ignores)
    assert [f.line for f in kept] == [3]
    assert [(e.id, e.status) for e in echoes] == [("S7", "applied")]


def test_other_rule_or_other_file_is_not_waived() -> None:
    ignores, _ = parse_ignores(f"/* design-ignore S7 reason: {REASON} */", "a.css")
    found = [finding("S9", 1), finding("S7", 1, file="b.css")]
    kept, echoes = apply_ignores(found, ignores)
    assert kept == found
    assert echoes[0].status == "unused"


def test_fail_findings_are_never_waived() -> None:
    ignores, _ = parse_ignores(f"/* design-ignore S2 reason: {REASON} */", "a.css")
    kept, echoes = apply_ignores([finding("S2", 2, severity="fail")], ignores)
    assert len(kept) == 1
    assert echoes[0].status == "refused"


def test_config_ids_waive_warn_everywhere_but_not_fail() -> None:
    found = [finding("S7", 9), finding("S2", 9, severity="fail")]
    kept, _ = apply_ignores(found, [], config_ids=("S7", "S2"))
    assert [f.id for f in kept] == ["S2"]


def test_bad_ignore_finding_is_valid_in_a_report() -> None:
    _, bad = parse_ignores("/* design-ignore S7 */", "a.css")
    checked = checked_block(tiers=["static"], widths=[], settings_source="defaults")
    report = build_report("check", bad, checked)
    assert validate_report(report) == []
