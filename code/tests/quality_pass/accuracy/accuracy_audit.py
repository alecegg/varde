"""Shared helpers for the A17-A19 accuracy audits.

Reference values live in ``fixtures/accuracy/README.md`` (derivation method,
set sizes) and in ``fixtures/accuracy/labels/*.json``. Nothing here derives a
reference from the facts engine; the engine is only ever the system under test.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from varde_code.quality_pass.facts import extract_facts
from varde_code.quality_pass.pathclass import PathPredicates, classify_path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures" / "accuracy"
# ``fixtures/accuracy/repo`` is a simulated repository; its fixture-relative
# paths are the paths the engine sees, which is what the A19 conventions and
# markers are keyed on.
SIMULATED_REPO = FIXTURES / "repo"

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".java": "java",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
}

# The seven release languages of the plan; TypeScript, JavaScript and TSX form
# one release language, so A17 is measured per entry of this mapping.
RELEASE_LANGUAGE = {
    "python": "python",
    "typescript": "typescript/javascript/tsx",
    "tsx": "typescript/javascript/tsx",
    "javascript": "typescript/javascript/tsx",
    "java": "java",
    "go": "go",
    "rust": "rust",
    "csharp": "csharp",
    "cpp": "cpp",
}

RATES: dict[str, list[str]] = {}


def labels(name: str) -> dict:
    """Load one ``labels/<name>.json`` reference file."""
    return json.loads((FIXTURES / "labels" / name).read_text())


def fixture_path(relative_path: str) -> Path:
    return FIXTURES / relative_path


def fixture_language(path: Path) -> str:
    return LANGUAGE_BY_SUFFIX[path.suffix]


def fixture_facts(relative_path: str) -> dict:
    """Run the facts engine over one fixture, keyed by its fixture-relative path."""
    path = fixture_path(relative_path)
    return extract_facts(path.read_text(), fixture_language(path), relative_path)


def function_key(function: dict) -> str:
    return (
        f"{function['owner']}.{function['name']}"
        if function["owner"]
        else function["name"]
    )


@dataclass(frozen=True)
class GeneratedSignals:
    """Engine signals for one simulated path, and the two decisions they support.

    ``raw`` is the detection signal (the A19 threshold applies to it): file
    markers, the path classification, or the minified exclusion. ``gate`` is
    the gate-mode exclusion decision with no base-ref allowlist and no extra
    generator signature, so a marker alone does not exclude.
    """

    markers: list[str]
    minified: bool
    by_path: bool
    by_gate: bool

    @property
    def raw(self) -> bool:
        return bool(self.markers) or self.minified or self.by_path

    @property
    def gate(self) -> bool:
        return self.minified or self.by_gate

    @property
    def raw_kinds(self) -> list[str]:
        kinds = []
        if self.markers:
            kinds.append("marker")
        if self.by_path:
            kinds.append("path")
        if self.minified:
            kinds.append("minified")
        return kinds


def generated_signals(relative_path: str) -> GeneratedSignals:
    """Run the engine over one simulated path and return both decisions."""
    path = SIMULATED_REPO / relative_path
    language = fixture_language(path)
    facts = extract_facts(path.read_text(), language, relative_path)
    markers = facts["markers"]
    path_class = classify_path(relative_path, PathPredicates(), language=language)
    gated = classify_path(
        relative_path,
        PathPredicates(generated_marker=bool(markers)),
        language=language,
        gate_mode=True,
    )
    return GeneratedSignals(
        markers=markers,
        minified=facts["excluded"] == "minified",
        by_path=path_class.generated or path_class.vendored,
        by_gate=gated.excluded,
    )


def record_rate(section: str, *lines: str) -> None:
    RATES[section] = list(lines)


def format_rates() -> list[str]:
    return [
        f"  {section}: {line}" for section, lines in RATES.items() for line in lines
    ]
