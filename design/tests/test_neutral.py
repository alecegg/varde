"""Project-neutrality: shipped package text must not name a specific project."""

import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
FORBIDDEN = ("runner", "ui-ux-standards", "style.css", "lib/ui", "_catalog", "--cf-")
SUFFIXES = {".py", ".md", ".toml", ".json", ".html", ".css", ".txt"}


def _shipped_files() -> list[Path]:
    roots = [PACKAGE / "src", PACKAGE / "README.md", PACKAGE / "pyproject.toml"]
    files: list[Path] = []
    for root in roots:
        found = [root] if root.is_file() else sorted(root.rglob("*"))
        files += [p for p in found if p.is_file() and p.suffix in SUFFIXES]
    return files


def test_shipped_files_are_found() -> None:
    names = {p.name for p in _shipped_files()}
    assert {"registry.py", "settings.py", "report.py", "README.md"} <= names


def test_no_project_specific_strings_in_shipped_files() -> None:
    hits = [
        f"{path.relative_to(PACKAGE)}: {term}"
        for path in _shipped_files()
        for term in FORBIDDEN
        if term in path.read_text(encoding="utf-8").lower()
    ]
    assert hits == []


def test_design_does_not_import_data() -> None:
    sources = "\n".join(p.read_text() for p in (PACKAGE / "src").rglob("*.py"))
    assert "varde_data" not in sources
    assert re.search(r"^\s*(import|from)\s+data\b", sources, re.MULTILINE) is None
