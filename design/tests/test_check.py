"""Pure orchestration: texts in, report dict out."""

from varde_design.check import MAX_FINDINGS, RENDER_NOT_RUN, check_texts
from varde_design.report import exit_code, validate_report
from varde_design.reports import survey_report, tokens_report
from varde_design.settings import Settings

PAGE = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    "<title>t</title></head><body><main><h1>Hi</h1></main></body></html>"
)
GRADIENT = (
    ".t{background:linear-gradient(red,blue);-webkit-background-clip:text;"
    "background-clip:text;color:transparent}"
)


BAD_IMG = (
    '<!doctype html><html lang="en"><head>'
    '<meta name="viewport" content="width=device-width">'
    "<title>t</title></head><body><h1>Hi</h1>"
    '<img src="a.png"></body></html>'
)
OPINION = Settings(profile="opinion")


def ids(report: dict) -> set[str]:
    return {f["id"] for f in report["findings"]}


def test_clean_page_reports_only_the_rendered_tier_as_not_run() -> None:
    report = check_texts({"a.html": PAGE}, Settings())
    assert validate_report(report) == []
    assert report["findings"] == []
    assert report["checked"]["not_run"] == [RENDER_NOT_RUN]
    assert exit_code(report) == 1


def test_static_only_clean_page_exits_zero() -> None:
    report = check_texts({"a.html": PAGE}, Settings(), static_only=True)
    assert exit_code(report) == 0


def test_fail_finding_exits_two_and_names_rule_and_file() -> None:
    report = check_texts({"a.html": BAD_IMG}, Settings(), static_only=True)
    assert "S6" in ids(report)
    assert exit_code(report) == 2
    assert report["findings"][0]["file"] == "a.html"


def test_css_file_runs_reduced_motion_check() -> None:
    css = ".a{transition:opacity 200ms ease}"
    report = check_texts({"a.css": css}, OPINION, static_only=True)
    assert "S10" in ids(report)


def test_reduced_motion_query_silences_it() -> None:
    css = (
        ".a{transition:opacity 200ms ease}"
        "@media (prefers-reduced-motion:reduce){.a{transition:none}}"
    )
    assert "S10" not in ids(check_texts({"a.css": css}, OPINION))


def test_skipped_files_become_not_run_entries() -> None:
    report = check_texts({}, Settings(), skipped=["x.html: not found"])
    not_run = report["checked"]["not_run"]
    assert "x.html: not found" in not_run
    assert "no .html or .css files to check" in not_run
    assert exit_code(report) == 1


def test_s7_without_tokens_is_not_run() -> None:
    css = ".a{color:#123456}"
    report = check_texts({"a.css": css}, OPINION, static_only=True)
    assert "S7: no tokens found" in report["checked"]["not_run"]


def test_s7_uses_tokens_from_extra_sheets() -> None:
    sheet = ":root{--fg:#111111}"
    css = ".a{color:#123456}"
    report = check_texts({"a.css": css}, OPINION, extra_sheets=[sheet])
    assert "S7" in ids(report)
    assert "S7: no tokens found" not in report["checked"]["not_run"]


def test_html_style_block_gets_token_rules_with_page_line() -> None:
    page = (
        "<!doctype html>\n<html lang='en'><head><style>\n"
        ":root{--fg:#111111}\n.a{color:#123456}\n</style></head><body></body></html>"
    )
    report = check_texts({"p.html": page}, OPINION, static_only=True)
    s7 = [f for f in report["findings"] if f["id"] == "S7"]
    assert [f["line"] for f in s7] == [4]


def test_ignore_is_applied_and_echoed() -> None:
    css = (
        ".a{color:#123456} "
        "/* design-ignore S7 reason: brand colour agreed with design */\n"
    )
    sheet = ":root{--fg:#111111}"
    report = check_texts({"a.css": css}, OPINION, extra_sheets=[sheet])
    assert "S7" not in ids(report)
    echo = report["data"]["ignores"]
    assert [(e["id"], e["status"]) for e in echo] == [("S7", "applied")]


def test_fail_finding_is_never_waived() -> None:
    page = BAD_IMG.replace(
        "<body>",
        "<body><!-- design-ignore S6 reason: this looks fine to the whole team -->",
    )
    report = check_texts({"a.html": page}, Settings(), static_only=True)
    assert "S6" in ids(report)
    assert report["data"]["ignores"][0]["status"] == "refused"


def test_short_ignore_reason_is_a_finding() -> None:
    css = ".a{color:red} /* design-ignore S7 reason: no */"
    report = check_texts({"a.css": css}, Settings(), static_only=True)
    assert "IGN" in ids(report)


def test_config_ignore_drops_the_rule() -> None:
    report = check_texts({"a.css": GRADIENT}, Settings(ignore=("S2",)))
    assert "S2" not in ids(report)


def test_profile_opinion_adds_s3() -> None:
    css = ".card{border-left:4px solid red;border-radius:8px}"
    core = check_texts({"a.css": css}, Settings())
    opinion = check_texts({"a.css": css}, Settings(profile="opinion"))
    assert "S3" not in ids(core)
    assert "S3" in ids(opinion)


def test_findings_are_capped_worst_first() -> None:
    css = "".join(f".a{i}{{font-size:8px}}\n" for i in range(60))
    report = check_texts(
        {"a.css": css, "b.html": BAD_IMG}, Settings(), static_only=True
    )
    assert len(report["findings"]) == MAX_FINDINGS
    assert report["findings"][0]["severity"] == "fail"
    assert report["checked"]["truncated"]["shown"] == MAX_FINDINGS
    assert report["checked"]["truncated"]["total"] > MAX_FINDINGS


def test_report_is_deterministic() -> None:
    files = {"a.css": GRADIENT, "b.html": PAGE}
    assert check_texts(files, Settings()) == check_texts(files, Settings())


def test_tokens_report_lists_resolved_values() -> None:
    css = ":root{--a:#111111;--b:var(--a)}"
    report = tokens_report({"t.css": css})
    assert validate_report(report) == []
    rows = {r["name"]: r for r in report["data"]["tokens"]}
    assert rows["--b"]["resolved"] == "#111111"
    assert exit_code(report) == 0


def test_tokens_report_without_tokens_exits_one() -> None:
    report = tokens_report({"t.css": ".a{color:red}"})
    assert report["checked"]["not_run"] == ["tokens: no tokens found"]
    assert exit_code(report) == 1


def test_survey_report_is_valid_and_truncation_exits_one() -> None:
    report, text = survey_report(["a.css", "index.html"], {"a.css": ":root{--a:1}"})
    assert validate_report(report) == []
    assert "tokens:" in text
    assert exit_code(report) == 0
    cut, _ = survey_report(["a.css"], {}, truncated=True)
    assert exit_code(cut) == 1
