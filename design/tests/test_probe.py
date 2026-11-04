"""Probe: not-run states without a browser, plus a few real renders (slow)."""

import sys
from pathlib import Path

import pytest
from varde_design.judge import judge_all
from varde_design.probe import INSTALL_HINT, NotRun, probe, target_url
from varde_design.settings import Settings

RULES = Path(__file__).parent / "fixtures" / "corpus" / "rules"
WIDTHS = (390, 1440)


def test_missing_target_is_not_run_with_hint() -> None:
    result = probe("/no/such/page.html", WIDTHS)
    assert isinstance(result, NotRun)
    message = result.message()
    assert message.startswith("render: not run (target not found")
    assert INSTALL_HINT in message


def test_hint_names_extra_and_browser_install() -> None:
    assert "varde-design[render]" in INSTALL_HINT
    assert "playwright install chromium" in INSTALL_HINT


def test_missing_playwright_is_not_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    page = tmp_path / "p.html"
    page.write_text("<p>x</p>")
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    result = probe(str(page), WIDTHS)
    assert result == NotRun("playwright is not installed")


def test_target_url_passes_urls_and_resolves_files(tmp_path: Path) -> None:
    page = tmp_path / "p.html"
    page.write_text("x")
    assert target_url("http://localhost:3000/") == "http://localhost:3000/"
    assert str(target_url(str(page))).startswith("file:///")


def _measure(rule: str, kind: str) -> dict:
    result = probe(str(RULES / rule / f"{kind}.html"), WIDTHS)
    assert not isinstance(result, NotRun), result.message()
    return result


@pytest.mark.slow
def test_one_launch_measures_every_width() -> None:
    metrics = _measure("R2", "clean")
    assert [w["width"] for w in metrics["widths"]] == [390, 1440]
    first = metrics["widths"][0]
    assert first["texts"] and first["controls"] == []
    assert first["texts"][0]["backdrop"]["layers"]


@pytest.mark.slow
def test_overflow_fixture_fails_at_each_width() -> None:
    findings = judge_all(_measure("R2", "defect"), Settings())
    assert [(f.id, f.width) for f in findings] == [("R2", 390), ("R2", 1440)]


@pytest.mark.slow
def test_scroll_container_fixture_is_clean() -> None:
    assert judge_all(_measure("R2", "clean"), Settings()) == []


@pytest.mark.slow
def test_page_errors_are_recorded_per_width() -> None:
    errors = _measure("R6", "defect")["widths"][0]["errors"]
    assert {e["kind"] for e in errors} == {"console", "pageerror"}
    assert all(set(e) == {"kind", "text", "url"} for e in errors)
    assert _measure("R6", "clean")["widths"][0]["errors"] == []


@pytest.mark.slow
def test_text_and_control_measurements_are_plain_data() -> None:
    low = _measure("R1", "defect")["widths"][0]["texts"]
    faint = next(t for t in low if t["text"].startswith("Updated"))
    assert faint["color"] == "rgba(170, 170, 170, 1.000)"
    assert faint["backdrop"]["layers"][-1] == "rgba(255, 255, 255, 1.000)"
    small = _measure("R3", "defect")["widths"][0]["controls"]
    assert sorted(c["width"] for c in small if c["tag"] == "button") == [24.0, 24.0]


@pytest.mark.slow
def test_text_layout_and_focus_measurements_are_plain_data() -> None:
    head = _measure("R4", "defect")["widths"][0]["headings"]
    assert head[0]["lines"] > 2
    font = _measure("R5", "defect")["widths"][0]["fonts"][0]
    assert (font["first"], font["available"]) == ("Zephyr Sans Pro", False)
    wide = _measure("R8", "defect")["widths"][-1]["paragraphs"]
    assert max(p["first_line_chars"] for p in wide) > 75
    narrow = _measure("R7", "clean")["widths"]
    assert narrow[0]["focus"] is None
    stops = narrow[-1]["focus"]["stops"]
    assert [s["tag"] for s in stops] == ["a", "button"]
    assert stops[0]["changes"][0]["count"] > 0
