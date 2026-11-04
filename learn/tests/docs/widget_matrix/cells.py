"""Matrix axes and cell definitions (pure; no browser)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

WIDTHS = (320, 375, 768, 1024, 1440)
SCHEMES = ("light", "dark")
MODES = (
    "default",
    "reduced-motion",
    "zoom200",
    "coarse",
    "forced-colors",
    "print",
    "nojs",
    "rtl",
)
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "widgets"
WIDGETS = ("chrome", "choice", "form", "ranking", "slider", "decision", "comment")
WIDGET_FIXTURES = ("normal.md", "stress.md")
PAGE_FIXTURES = {
    "page-header.md": "page_header",
    "page-header-stress.md": "page_header",
}  # whole-page chrome, no blocks
WALK_MODES = ("default", "reduced-motion", "zoom200", "coarse", "nojs", "rtl")


@dataclass(frozen=True)
class Cell:
    family: str
    fixture: str
    width: int
    scheme: str
    mode: str

    @property
    def id(self) -> str:
        stem = self.fixture.removesuffix(".md")
        return f"{self.family}-{stem}-w{self.width}-{self.scheme}-{self.mode}"

    @property
    def page_key(self) -> tuple[str, int, str, str]:
        return (self.fixture, self.width, self.scheme, self.mode)


def rich_family(fixture: str) -> str | None:
    """`rich-chart.md` and `rich-chart-stress.md` hold family `rich-chart`."""
    stem = fixture.removesuffix(".md").removesuffix("-stress")
    return stem if stem.startswith("rich-") else None


def families_in(fixture: str) -> tuple[str, ...]:
    rich = rich_family(fixture)
    if fixture in PAGE_FIXTURES:
        return (PAGE_FIXTURES[fixture],)
    return (rich,) if rich else WIDGETS


def scope_for(family: str) -> dict[str, str | None]:
    """Selector scope the audit runs in: chrome is everything outside `.vb`."""
    if family in ("chrome", *PAGE_FIXTURES.values()):
        return {"inside": None, "outside": ".vb"}
    if family.startswith("rich-"):
        return {"inside": ".vb", "outside": None}
    return {"inside": f".vb.{family}", "outside": None}


def fixture_names(directory: Path = FIXTURES) -> tuple[str, ...]:
    rich = sorted(p.name for p in directory.glob("rich-*.md"))
    return (*WIDGET_FIXTURES, *PAGE_FIXTURES, *rich)


def all_cells(directory: Path = FIXTURES) -> list[Cell]:
    return [
        Cell(family, fixture, width, scheme, mode)
        for fixture in fixture_names(directory)
        for family in families_in(fixture)
        for width in WIDTHS
        for scheme in SCHEMES
        for mode in MODES
    ]
