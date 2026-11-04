"""Integrity controls for the quality gate.

Pure helpers (config diffs, severity downgrades, calibration pin, suppression
counting) are kept apart from the small readers that touch git, the index and
the filesystem. Nothing here changes the fast index.
"""

from __future__ import annotations

import re
import sqlite3
import tempfile
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_code.git import run_git, run_git_bytes
from varde_code.quality_score.calibration import Calibration
from varde_code.query.params import QueryError
from varde_code.rules.finding import Finding
from varde_code.rules.model import Rule
from varde_code.rules.suppress import parse_suppressions
from varde_code.scan.quality_scores import REPO_SCOPE

QUALITY_PREFIX = "quality-"
CONFIG_DIR = ".varde-code"
PIN_FILE = f"{CONFIG_DIR}/quality-pin.toml"
OVERRIDES_FILE = f"{CONFIG_DIR}/overrides.toml"
TESTS_SCOPE = "tests"
TOOLING_SCOPE = "tooling"

ConfigFiles = dict[str, str]


def _diagnostic(
    rule_id: str, message: str, *, blocking: bool, path: str = "."
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "path": path,
        "message": message,
        "blocking": blocking,
        "severity": "error" if blocking else "warning",
        "source": "rules",
    }


# --- scopes -----------------------------------------------------------------


def scope_name(is_test: bool, is_tooling: bool) -> str:
    """Tests win over tooling; everything else is the repo scope."""
    if is_test:
        return TESTS_SCOPE
    return TOOLING_SCOPE if is_tooling else REPO_SCOPE


def read_path_scopes(conn: sqlite3.Connection, root: Path) -> dict[str, str]:
    """Map each non-repo indexed path (root-relative) to its scope."""
    canonical = root.resolve()
    result: dict[str, str] = {}
    for path, is_test, is_tooling in conn.execute(
        "SELECT path, is_test_path, is_tooling_path FROM files"
    ):
        name = scope_name(bool(is_test), bool(is_tooling))
        if name != REPO_SCOPE:
            result[_relative(path, canonical)] = name
    return result


def _relative(path: str, canonical_root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(canonical_root).as_posix()
    except ValueError:
        return path


# --- config from a base ref -------------------------------------------------


def read_ref_config(root: Path, ref: str) -> ConfigFiles | None:
    """Return every file under ``.varde-code`` at ``ref``; None when ref is missing."""
    if run_git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], root) is None:
        return None
    listing = run_git(["ls-tree", "-r", "--name-only", ref, "--", CONFIG_DIR], root)
    if listing is None:
        return None
    files: ConfigFiles = {}
    for name in listing.splitlines():
        content = run_git_bytes(["show", f"{ref}:{name}"], root)
        if content is None:
            return None
        files[name] = content.decode("utf-8", errors="replace")
    return files


def read_working_config(root: Path) -> ConfigFiles:
    base = root / CONFIG_DIR
    if not base.is_dir():
        return {}
    files: ConfigFiles = {}
    for path in sorted(base.rglob("*")):
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_text(
                encoding="utf-8", errors="replace"
            )
    return files


def changed_config_files(base: Mapping[str, str], head: Mapping[str, str]) -> list[str]:
    return sorted(name for name in {*base, *head} if base.get(name) != head.get(name))


def config_changed_diagnostic(
    base: Mapping[str, str], head: Mapping[str, str]
) -> dict[str, Any] | None:
    """Blocking when the PR changes rules, thresholds, overrides or the pin."""
    changed = changed_config_files(base, head)
    if not changed:
        return None
    return _diagnostic(
        "config-changed",
        "quality configuration differs from the base ref ("
        + ", ".join(changed)
        + "); findings use the base configuration",
        blocking=True,
        path=changed[0],
    )


def missing_ref_diagnostic(option: str, ref: str) -> dict[str, Any]:
    return _diagnostic(
        "config-changed",
        f"{option} ref {ref!r} was not found; analysis is incomplete",
        blocking=True,
    )


def write_config(files: Mapping[str, str], dest: Path) -> None:
    for name, content in files.items():
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def load_base_rules(files: Mapping[str, str], load: Callable[[Path], Any]) -> Any:
    """Run ``load`` (a rules loader) against a temp root holding the base config."""
    with tempfile.TemporaryDirectory(prefix="varde-base-config-") as tmp:
        write_config(files, Path(tmp))
        return load(Path(tmp))


# --- severity downgrades ----------------------------------------------------


@dataclass(frozen=True)
class Downgrade:
    rule_id: str
    old: str
    new: str
    reason: str | None


def override_reasons(files: Mapping[str, str]) -> dict[str, str | None]:
    """Read ``reason`` per rule id from the repo overrides file (None if absent)."""
    try:
        document = tomllib.loads(files.get(OVERRIDES_FILE, ""))
    except tomllib.TOMLDecodeError:
        return {}
    entries = document.get("rules")
    if not isinstance(entries, dict):
        return {}
    result: dict[str, str | None] = {}
    for rule_id, entry in entries.items():
        reason = entry.get("reason") if isinstance(entry, dict) else None
        result[rule_id] = (
            reason.strip() if isinstance(reason, str) and reason.strip() else None
        )
    return result


def severity_downgrades(
    builtin: Iterable[Rule],
    effective: Iterable[Rule],
    disabled_ids: Iterable[str],
    reasons: Mapping[str, str | None],
) -> list[Downgrade]:
    """Quality rules whose effective severity is lower than the built-in one."""
    now = {rule.id: rule.severity for rule in effective}
    off = set(disabled_ids)
    result = []
    for rule in builtin:
        if not rule.id.startswith(QUALITY_PREFIX):
            continue
        if rule.id in off:
            result.append(
                Downgrade(rule.id, rule.severity.value, "off", reasons.get(rule.id))
            )
            continue
        new = now.get(rule.id, rule.severity)
        if new.rank < rule.severity.rank:
            result.append(
                Downgrade(rule.id, rule.severity.value, new.value, reasons.get(rule.id))
            )
    return sorted(result, key=lambda item: item.rule_id)


def downgrade_diagnostic(item: Downgrade) -> dict[str, Any]:
    reason = f"reason: {item.reason}" if item.reason else "missing reason"
    return _diagnostic(
        "quality-severity-downgrade",
        f"{item.rule_id} lowered from {item.old} to {item.new} ({reason})",
        blocking=False,
        path=OVERRIDES_FILE,
    )


# --- calibration pin --------------------------------------------------------


def read_pin(files: Mapping[str, str]) -> dict[str, str] | None:
    try:
        document = tomllib.loads(files.get(PIN_FILE, ""))
    except tomllib.TOMLDecodeError:
        return None
    pin = {
        key: document[key]
        for key in ("calibration_id", "formula")
        if isinstance(document.get(key), str)
    }
    return pin or None


def formula_major(formula: str) -> str:
    match = re.search(r"\d+", formula)
    return match.group(0) if match else formula


def pin_differences(
    pin: Mapping[str, str] | None, calibration: Calibration
) -> list[str]:
    """Names of pinned values that differ from the loaded calibration."""
    if not pin:
        return []
    differences = []
    pinned_id = pin.get("calibration_id")
    if pinned_id is not None and pinned_id != calibration.id:
        differences.append("calibration_id")
    pinned_formula = pin.get("formula")
    if pinned_formula is not None and formula_major(pinned_formula) != formula_major(
        calibration.formula
    ):
        differences.append("formula")
    return differences


def check_pin(
    pin: Mapping[str, str] | None, calibration: Calibration, *, allow_change: bool
) -> None:
    differences = pin_differences(pin, calibration)
    if not differences or allow_change:
        return
    raise QueryError(
        "calibration_pin_mismatch",
        f"{PIN_FILE} pins {dict(pin or {})} but the loaded calibration is "
        f"{calibration.id} ({calibration.formula}); differs in "
        f"{', '.join(differences)}. Pass allowCalibrationChange to accept it, or "
        "preview with migratePreview. The pinned calibration was replaced by the "
        "shipped cal-2, and all languages are currently non-gating (info)",
    )


def migrate_preview(
    pin: Mapping[str, str] | None, calibration: Calibration
) -> dict[str, Any]:
    differences = pin_differences(pin, calibration)
    return {
        "pinned": dict(pin) if pin else None,
        "current": {"calibration_id": calibration.id, "formula": calibration.formula},
        "differs": differences,
        "refused_without_flag": bool(differences),
        "next_step": (
            "set allowCalibrationChange for one run, review the score changes, then "
            f"update {PIN_FILE}; the pinned calibration was replaced by the shipped "
            "cal-2 and all languages are currently non-gating (info)"
            if differences
            else "pin matches the loaded calibration; nothing to migrate"
        ),
    }


# --- suppression ------------------------------------------------------------


def is_quality_finding(finding: Finding) -> bool:
    return finding.rule_id.startswith(QUALITY_PREFIX)


def _suppressed(finding: Finding, root: Path) -> bool:
    file = finding.location.file
    if file == ".":
        return False
    path = Path(file) if Path(file).is_absolute() else root / file
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return False
    line = finding.location.span.start_line
    return any(
        directive.matches(line, finding.rule_id)
        for directive in parse_suppressions(source, path)
    )


def count_quality_suppressions(
    findings: Iterable[Finding], root: Path
) -> list[tuple[str, str, int]]:
    """Count quality findings an inline directive would have hidden.

    Gate mode ignores these directives; the count feeds ``quality-suppressed``.
    """
    counts: dict[tuple[str, str], int] = {}
    for finding in findings:
        if not is_quality_finding(finding) or not _suppressed(finding, root):
            continue
        evidence = finding.evidence if isinstance(finding.evidence, dict) else {}
        key = (str(evidence.get("scope", REPO_SCOPE)), finding.rule_id)
        counts[key] = counts.get(key, 0) + 1
    return [(scope, rule_id, n) for (scope, rule_id), n in sorted(counts.items())]


def write_suppression_counts(
    conn: sqlite3.Connection, rows: Iterable[tuple[str, str, int]]
) -> None:
    conn.executemany("INSERT INTO quality_suppressions VALUES (?, ?, ?)", rows)


def filter_inline_suppressions(
    findings: list[Finding],
    root: Path,
    filter_findings: Callable[[list[Finding], Path], tuple[list[Finding], list[Any]]],
) -> tuple[list[Finding], list[Any]]:
    """Apply inline suppression to non-quality findings only, keeping order."""
    others = [f for f in findings if not is_quality_finding(f)]
    kept, stale = filter_findings(others, root)
    kept_ids = {id(f) for f in kept}
    return [f for f in findings if is_quality_finding(f) or id(f) in kept_ids], stale
