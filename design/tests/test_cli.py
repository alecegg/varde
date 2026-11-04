import json
import shutil
from pathlib import Path

import pytest
from varde_design.cli import help_text, run
from varde_design.module import register
from varde_design.report import validate_report

FIXTURES = Path(__file__).parent / "fixtures" / "corpus" / "rules"
GRADIENT = (
    ".t{background:linear-gradient(red,blue);-webkit-background-clip:text;"
    "background-clip:text;color:transparent}\n"
)

BAD_IMG = (
    '<!doctype html><html lang="en"><head>'
    '<meta name="viewport" content="width=device-width">'
    "<title>t</title></head><body><h1>Hi</h1>"
    '<img src="a.png"></body></html>'
)


def test_help_exits_zero(capsys) -> None:
    assert register().run(["--help"]) == 0
    assert "Usage: varde design" in capsys.readouterr().out


def test_unknown_argument_exits_two(capsys) -> None:
    assert run(["bogus"]) == 2
    assert "unknown argument: bogus" in capsys.readouterr().out


def test_check_help_lists_flags_tiers_and_exit_codes(capsys) -> None:
    assert run(["check", "--help"]) == 0
    out = capsys.readouterr().out
    for word in (
        "--static-only",
        "--config",
        "--tokens",
        "fail",
        "warn",
        "Exit codes: 0 clean, 1",
    ):
        assert word in out
    assert "Usage: varde design check" in help_text("design check")


def run_json(capsys, *argv: str) -> tuple[int, dict]:
    code = run([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_check_json_is_schema_valid_and_exit_two_on_fail(tmp_path, capsys) -> None:
    (tmp_path / "a.html").write_text(BAD_IMG)
    code, report = run_json(capsys, "check", str(tmp_path / "a.html"), "--static-only")
    assert code == 2
    assert report["schema"] == 1
    assert validate_report(report) == []
    assert {f["id"] for f in report["findings"]} >= {"S6"}


def test_check_text_output_names_file_rule_and_checked_block(tmp_path, capsys) -> None:
    (tmp_path / "a.html").write_text(BAD_IMG)
    assert run(["check", str(tmp_path / "a.html"), "--static-only"]) == 2
    out = capsys.readouterr().out
    assert "a.html:1 fail S6" in out
    assert "checked: tiers static" in out


def test_clean_static_only_exits_zero_and_default_exits_one(tmp_path, capsys) -> None:
    (tmp_path / "ok.css").write_text(":root{--a:#111111}\nbody{margin:0}\n")
    assert run(["check", str(tmp_path), "--static-only"]) == 0
    assert run(["check", str(tmp_path)]) == 1
    capsys.readouterr()


def test_missing_path_exits_one_with_reason(tmp_path, capsys) -> None:
    code, report = run_json(capsys, "check", str(tmp_path / "nope.html"))
    assert code == 1
    assert any("not found" in item for item in report["checked"]["not_run"])


def test_oversized_file_is_skipped_not_read(tmp_path, capsys) -> None:
    big = tmp_path / "big.css"
    big.write_text("a{color:red}\n" * 50_000)
    code, report = run_json(capsys, "check", str(big), "--static-only")
    assert code == 1
    assert any("over 512 KB" in item for item in report["checked"]["not_run"])


def test_unreadable_file_is_reported(tmp_path, capsys) -> None:
    locked = tmp_path / "locked.css"
    locked.write_text("a{}")
    locked.chmod(0)
    try:
        code, report = run_json(capsys, "check", str(locked), "--static-only")
    finally:
        locked.chmod(0o644)
    assert code == 1
    assert any("unreadable" in item for item in report["checked"]["not_run"])


def test_url_target_needs_rendered_tier(capsys) -> None:
    code, report = run_json(capsys, "check", "https://example.com/")
    assert code == 1
    assert any("rendered tier" in item for item in report["checked"]["not_run"])


def test_ignore_echo_in_json_and_text(tmp_path, capsys) -> None:
    css = (
        ":root{--fg:#111111}\n"
        ".a{color:#123456} "
        "/* design-ignore S7 reason: brand colour agreed with design */\n"
    )
    (tmp_path / "a.css").write_text(css)
    args = ("check", str(tmp_path / "a.css"), "--static-only", "--profile", "opinion")
    code, report = run_json(capsys, *args)
    assert code == 0
    assert report["data"]["ignores"][0]["status"] == "applied"
    run(list(args))
    assert "ignore applied:" in capsys.readouterr().out


def test_config_file_is_discovered_and_reported(tmp_path, capsys) -> None:
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "varde-design.toml").write_text('ignore = ["S2"]\n')
    (tmp_path / "a.css").write_text(":root{--a:#111111}\n" + GRADIENT)
    code, report = run_json(capsys, "check", str(tmp_path / "a.css"), "--static-only")
    assert code == 0
    assert report["checked"]["settings_source"] == "varde-design.toml"


def test_config_flag_and_invalid_config(tmp_path, capsys) -> None:
    cfg = tmp_path / "x.toml"
    cfg.write_text("bogus = 1\n")
    (tmp_path / "a.css").write_text(GRADIENT)
    assert run(["check", str(tmp_path / "a.css"), "--config", str(cfg)]) == 2
    assert "unknown setting: bogus" in capsys.readouterr().out


def test_profile_flag_overrides_config(tmp_path, capsys) -> None:
    (tmp_path / "a.css").write_text(".card{border-left:4px solid red}\n")
    _, core = run_json(capsys, "check", str(tmp_path / "a.css"), "--static-only")
    _, opinion = run_json(
        capsys, "check", str(tmp_path / "a.css"), "--profile", "opinion"
    )
    assert "S3" not in {f["id"] for f in core["findings"]}
    assert "S3" in {f["id"] for f in opinion["findings"]}


def test_usage_errors_exit_two(capsys) -> None:
    assert run(["check", "--bogus"]) == 2
    assert run(["check", "--profile", "loud"]) == 2
    assert run(["check", "--width", "a"]) == 2
    assert run(["check", "--config"]) == 2
    capsys.readouterr()


def test_tokens_command(tmp_path, capsys) -> None:
    (tmp_path / "t.css").write_text(":root{--a:#111111;--b:var(--a)}\n")
    code, report = run_json(capsys, "tokens", str(tmp_path))
    assert code == 0
    assert validate_report(report) == []
    assert report["command"] == "tokens"
    run(["tokens", str(tmp_path)])
    assert "--b: #111111" in capsys.readouterr().out


def test_tokens_command_none_found_exits_one(tmp_path, capsys) -> None:
    (tmp_path / "t.css").write_text("a{color:red}\n")
    assert run(["tokens", str(tmp_path)]) == 1
    assert "no tokens found" in capsys.readouterr().out


def test_survey_command(tmp_path, capsys) -> None:
    (tmp_path / "t.css").write_text(":root{--a:1}\n")
    (tmp_path / "index.html").write_text("<html></html>")
    code, report = run_json(capsys, "survey", str(tmp_path))
    assert code == 0
    assert validate_report(report) == []
    assert report["command"] == "survey"
    run(["survey", str(tmp_path)])
    assert "tokens: 1 custom properties" in capsys.readouterr().out


def test_survey_missing_path_exits_one(tmp_path, capsys) -> None:
    code, report = run_json(capsys, "survey", str(tmp_path / "nope"))
    assert code == 1
    assert any("not a folder" in item for item in report["checked"]["not_run"])


def test_json_output_is_identical_across_runs(tmp_path, capsys) -> None:
    (tmp_path / "a.css").write_text(GRADIENT)
    first = run_json(capsys, "check", str(tmp_path), "--static-only")
    second = run_json(capsys, "check", str(tmp_path), "--static-only")
    assert first == second


RULE_IDS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "R7"]


@pytest.mark.parametrize("rule", RULE_IDS)
def test_corpus_pair_through_the_cli(rule, tmp_path, capsys) -> None:
    for kind in ("defect", "clean"):
        shutil.copy(FIXTURES / rule / f"{kind}.html", tmp_path / f"{kind}.html")
    _, report = run_json(capsys, "check", str(tmp_path), "--profile", "opinion")
    by_file: dict[str, set[str]] = {}
    for finding in report["findings"]:
        by_file.setdefault(Path(finding["file"]).name, set()).add(finding["id"])
    assert rule in by_file.get("defect.html", set())
    assert rule not in by_file.get("clean.html", set())


HTML_PAGE = "<!doctype html><title>t</title><p>hi</p>"


@pytest.mark.slow
@pytest.mark.parametrize(
    ("kind", "expect_ids", "code"),
    [("defect", {"R6"}, 2), ("clean", set(), None)],
)
def test_check_with_render_tier_on_r6_fixtures(kind, expect_ids, code, capsys) -> None:
    page = FIXTURES / "R6" / f"{kind}.html"
    exit_code, report = run_json(capsys, "check", str(page), "--width", "390,1440")
    ids = {f["id"] for f in report["findings"]} & {"R6"}
    assert ids == expect_ids
    assert report["checked"]["rendered"] is True
    assert report["checked"]["widths"] == [390, 1440]
    assert "rendered" in report["checked"]["tiers"]
    assert validate_report(report) == []
    if code:
        assert exit_code == code
        r6 = [f for f in report["findings"] if f["id"] == "R6"]
        assert all("390, 1440px" in f["message"] for f in r6)


def test_missing_browser_keeps_not_run_entry(tmp_path, monkeypatch, capsys) -> None:
    from varde_design import render_tier
    from varde_design.probe import NotRun

    monkeypatch.setattr(render_tier, "probe", lambda t, w: NotRun("no chromium"))
    page = tmp_path / "p.html"
    page.write_text(HTML_PAGE)
    code, report = run_json(capsys, "check", str(page))
    assert code in {1, 2}
    assert report["checked"]["rendered"] is False
    assert report["checked"]["tiers"] == ["static"]
    assert any(
        "render: not run (no chromium)" in n for n in report["checked"]["not_run"]
    )


def test_static_only_skips_the_probe(tmp_path, monkeypatch, capsys) -> None:
    from varde_design import render_tier

    def boom(*args):
        raise AssertionError("probe must not run")

    monkeypatch.setattr(render_tier, "probe", boom)
    page = tmp_path / "p.html"
    page.write_text(HTML_PAGE)
    _, report = run_json(capsys, "check", str(page), "--static-only")
    assert report["checked"]["rendered"] is False
    assert not any("render" in n for n in report["checked"]["not_run"])
