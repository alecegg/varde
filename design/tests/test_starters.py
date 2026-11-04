import json
import re
from pathlib import Path

import pytest
from varde_design.cli import run

STARTERS = (
    Path(__file__).parents[1]
    / "src"
    / "varde_design"
    / "skills"
    / "varde-design"
    / "starters"
)
FILES = sorted(STARTERS.glob("*.html"))
BYTE_CAP = 3200
RUNNER_NAMES = ("runner", "varde", "hallmark", "ui-ux-standards", "_catalog", "lib/ui")


def test_four_starters_exist() -> None:
    names = {path.stem for path in FILES}
    assert names == {"app-screen", "reading-page", "landing-page"}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_starter_byte_cap(path: Path) -> None:
    assert path.stat().st_size <= BYTE_CAP


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_starter_provenance(path: Path) -> None:
    text = path.read_text().lower()
    assert not re.search(r"https?://|//cdn|@import", text)
    assert "@font-face" not in text
    for name in RUNNER_NAMES:
        assert name not in text, name


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_starter_declares_token_basics(path: Path) -> None:
    text = path.read_text()
    for token in ("--s1:4px", "--target:44px", "--ring:", "--font:system-ui"):
        assert token in text
    assert "prefers-reduced-motion" in text


def check_json(capsys, path: Path, *extra: str) -> tuple[int, dict]:
    code = run(["check", str(path), "--json", *extra])
    return code, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_starter_static_tier_is_clean(path: Path, capsys) -> None:
    code, report = check_json(capsys, path, "--static-only")
    assert report["findings"] == []
    assert code == 0


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_starter_rendered_tier_is_clean(path: Path, capsys) -> None:
    pytest.importorskip(
        "playwright", reason="playwright missing: rendered tier skipped"
    )
    code, report = check_json(capsys, path)
    if report["checked"]["not_run"]:
        pytest.skip(f"rendered tier not run: {report['checked']['not_run']}")
    assert report["findings"] == []
    assert code == 0
