"""Scoring, saving and data access for the baseline page (no HTTP here)."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_core.paths import varde_config_dir

from ..baseline_tests import LANGUAGES, TestResult, run_tests, toolchain_available
from ..breakdown import breakdown
from ..calibration import Calibration, load_calibration
from ..calibration import overlay as ov
from ..file_advisories import delegation_advisory, fragmentation_advisory
from ..file_facts import exact_facts
from ..raw_measure import raw_measure_sources
from ..refactor_line import limits_of, monolith_advisory
from ..scoring import explain, score_scope
from ..user_view import user_view, with_debug

MAX_CODE_BYTES = 200 * 1024
DEFAULT_DATA = Path(__file__).resolve().parents[1] / "baseline_data"
SOURCE_NAMES = {lang: spec.solution for lang, spec in LANGUAGES.items()}
SUPPORT_FILES = {"csharp": ("Baseline.csproj", "Harness.cs")}


class MissingToolchainError(RuntimeError):
    """The language's test toolchain is not installed."""


class TestsFailedError(RuntimeError):
    """The behaviour tests did not pass."""

    __test__ = False  # not a pytest class


@dataclass(frozen=True)
class BaselineData:
    """Shipped problems, agreed code, tests and calibration under one root."""

    root: Path

    @property
    def calibration_path(self) -> Path:
        return self.root / "cal-1.toml"

    def problems(self) -> list[str]:
        base = self.root / "problems"
        return sorted(
            p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("_")
        )

    def statement(self, problem: str) -> str:
        return (self.root / "problems" / problem / "prompt.txt").read_text().strip()

    def agreed_dir(self, problem: str, language: str) -> Path:
        return self.root / "agreed" / problem / language

    def agreed_code(self, problem: str, language: str) -> str:
        return (self.agreed_dir(problem, language) / SOURCE_NAMES[language]).read_text()

    def test_file(self, problem: str, language: str) -> Path:
        name = LANGUAGES[language].test
        return self.root / "problems" / problem / language / name

    def support(self, language: str) -> dict[str, str]:
        base = self.root / "problems" / "_support" / language
        return {n: (base / n).read_text() for n in SUPPORT_FILES.get(language, ())}

    def corpus(self, language: str) -> dict[str, list[int]]:
        path = self.root / "corpus.json"
        if not path.is_file():
            return {}
        return json.loads(path.read_text()).get(language, {})

    def has(self, problem: str, language: str) -> bool:
        return (
            language in LANGUAGES
            and problem in self.problems()
            and (self.agreed_dir(problem, language) / SOURCE_NAMES[language]).is_file()
        )


def overlay_paths(language: str) -> tuple[Path, Path]:
    """The overlay file and its sibling samples directory."""
    base = varde_config_dir() / "quality"
    return base / f"overlay-{language}.toml", base / f"overlay-{language}.samples"


def effective(
    data: BaselineData, language: str
) -> tuple[Calibration, ov.Overlay | None]:
    parent = load_calibration(data.calibration_path)
    path, _ = overlay_paths(language)
    if not path.is_file():
        return parent, None
    overlay = ov.read_overlay(path.read_text(), parent)
    return ov.effective_calibration(parent, overlay), overlay


def score_code(
    code: str,
    language: str,
    calibration: Calibration,
    tests_passed: bool | None,
    debug: bool,
) -> dict[str, Any]:
    """Source -> whitelisted 0-100 user view; raw scorer fields only if ``debug``."""
    record = exact_facts(
        code, language, f"code{os.path.splitext(SOURCE_NAMES[language])[1]}"
    )
    scored = score_scope([record], calibration)
    payload = explain(scored)
    payload["calibration"] = calibration.output_label
    rows = breakdown(scored, calibration, [record])
    entry = calibration.languages.get(language)
    advisory = monolith_advisory(record, limits_of(entry.parameters)) if entry else None
    view = user_view(
        payload,
        rows,
        tests_passed,
        monolith=advisory,
        file_advisories={
            "delegation": delegation_advisory(record),
            "fragmentation": fragmentation_advisory(record),
        },
    )
    return with_debug(view, {**payload, "breakdown": rows}) if debug else view


def run_behaviour_tests(
    data: BaselineData, problem: str, language: str, code: str
) -> TestResult | None:
    """Run the problem's tests on ``code`` in the sandboxed runner."""
    with tempfile.TemporaryDirectory(prefix="baseline-code-") as temp:
        (Path(temp) / SOURCE_NAMES[language]).write_text(code)
        return run_tests(
            language,
            Path(temp),
            data.test_file(problem, language),
            data.support(language),
        )


def tests_state(result: TestResult | None) -> bool | None:
    return None if result is None else result.ok


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _samples_of(
    overlay: ov.Overlay | None, samples_dir: Path, skip: str
) -> dict[str, str]:
    """Saved code by problem, minus ``skip`` (about to be replaced)."""
    if overlay is None:
        return {}
    return {
        s.problem: (samples_dir / s.code_path).read_text()
        for s in overlay.samples
        if s.problem != skip
    }


def _rows_of(code: str, language: str) -> list[dict[str, Any]]:
    name = SOURCE_NAMES[language]
    return raw_measure_sources({name: code.encode()}, language)["functions"]


def save_example(
    data: BaselineData, problem: str, language: str, code: str
) -> tuple[Path, Calibration]:
    """Run tests, add ``code`` as an example, write the overlay; return it."""
    if not toolchain_available(language):
        raise MissingToolchainError(language)
    result = run_behaviour_tests(data, problem, language, code)
    if result is None or not result.ok:
        raise TestsFailedError(problem)
    parent = load_calibration(data.calibration_path)
    path, samples_dir = overlay_paths(language)
    current = ov.read_overlay(path.read_text(), parent) if path.is_file() else None
    codes = _samples_of(current, samples_dir, problem) | {problem: code}
    codes = dict(sorted(codes.items()))
    thresholds = ov.calibrate(
        ov.default_region(parent, language),
        [_rows_of(text, language) for text in codes.values()],
        data.corpus(language),
    )
    samples = [_sample_entry(name, text, language) for name, text in codes.items()]
    overlay = ov.build_overlay(parent, language, samples, thresholds, _now())
    samples_dir.mkdir(parents=True, exist_ok=True)
    for sample, text in zip(samples, codes.values(), strict=True):
        _atomic_write(samples_dir / sample.code_path, text)
    _atomic_write(path, ov.render_overlay(overlay))
    return path, ov.effective_calibration(parent, overlay)


def reset_overlay(language: str) -> bool:
    """Delete the language's overlay and saved examples; True if one existed."""
    path, samples_dir = overlay_paths(language)
    existed = path.is_file()
    path.unlink(missing_ok=True)
    if samples_dir.is_dir():
        for item in samples_dir.iterdir():
            item.unlink()
        samples_dir.rmdir()
    return existed


def _sample_entry(problem: str, code: str, language: str) -> ov.Sample:
    suffix = os.path.splitext(SOURCE_NAMES[language])[1]
    return ov.Sample(problem, sha256(code), f"{problem}{suffix}")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(handle, "w") as stream:
            stream.write(text)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
