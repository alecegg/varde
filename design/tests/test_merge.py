"""Pure merge and dedupe of static and rendered findings, plus the R6 ignore list."""

import pytest
from test_render_rules import _metrics
from varde_design.judge import judge
from varde_design.merge import dedupe_widths, dev_server_notes, merge_findings
from varde_design.report import Finding
from varde_design.settings import Settings, SettingsError, parse_settings


def _r6(width: int, text: str = "boom", file: str = "a.html") -> Finding:
    return Finding(
        id="R6",
        severity="fail",
        tier="rendered",
        file=file,
        width=width,
        snippet=text,
        message=f"Page error: {text}",
    )


def _r7(tier: str) -> Finding:
    return Finding(id="R7", severity="fail", tier=tier, file="a.html", message="focus")


def test_r6_repeated_across_widths_becomes_one_finding_naming_them() -> None:
    merged = dedupe_widths([_r6(1440), _r6(390), _r6(768)])
    assert len(merged) == 1
    assert merged[0].width == 390
    assert merged[0].message.endswith("(at 390, 768, 1440px)")


def test_single_width_and_distinct_errors_are_untouched() -> None:
    one = [_r6(390, "a"), _r6(390, "b")]
    assert dedupe_widths(one) == one


def test_other_rules_are_never_deduplicated() -> None:
    r2 = [
        Finding(
            id="R2",
            severity="fail",
            tier="rendered",
            file="a.html",
            width=w,
            message="overflow",
        )
        for w in (390, 1440)
    ]
    assert dedupe_widths(r2) == r2


def test_same_error_on_two_files_stays_two_findings() -> None:
    merged = dedupe_widths([_r6(390, file="a.html"), _r6(390, file="b.html")])
    assert len(merged) == 2


def test_merge_drops_rendered_r7_when_static_r7_present() -> None:
    merged = merge_findings([_r7("static")], [_r7("rendered"), _r6(390)])
    assert [(f.id, f.tier) for f in merged] == [("R7", "static"), ("R6", "rendered")]


def test_merge_keeps_rendered_r7_without_static_r7() -> None:
    merged = merge_findings([], [_r7("rendered")])
    assert [(f.id, f.tier) for f in merged] == [("R7", "rendered")]


def test_dev_server_note_names_the_page() -> None:
    pages = [
        {"target": "a.html", "widths": [{"dev_server": False}]},
        {"target": "b.html", "widths": [{"dev_server": True}]},
    ]
    notes = dev_server_notes(pages)
    assert len(notes) == 1 and "b.html" in notes[0] and "dev-server build" in notes[0]


def _errors(*items: tuple[str, str]) -> dict:
    return _metrics(errors=[{"kind": "console", "text": t, "url": u} for t, u in items])


def test_ignore_console_drops_matching_errors_only() -> None:
    metrics = _errors(("ad tracker failed", ""), ("real bug", ""))
    settings = Settings(ignore_console=("tracker",))
    assert [f.snippet for f in judge(metrics, 390, settings)] == ["real bug"]


def test_favicon_default_holds_without_config() -> None:
    metrics = _errors(("404", "http://x/favicon.ico"))
    assert judge(metrics, 390, Settings()) == []


def test_ignore_console_setting_validates_regex() -> None:
    assert parse_settings({"ignore_console": ["a.*b"]}).ignore_console == ("a.*b",)
    with pytest.raises(SettingsError, match="bad regex"):
        parse_settings({"ignore_console": ["("]})
