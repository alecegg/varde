"""Severity overrides and built-in pack management helpers."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from varde_core.paths import varde_config_dir

from varde_code.rules.model import Diagnostic, Rule, Severity


@dataclass(frozen=True)
class SeedResult:
    file_name: str
    path: Path
    written: bool
    skipped_existing: bool


@dataclass(frozen=True)
class RemoveResult:
    file_name: str
    path: Path
    removed: bool
    skipped_modified: bool


@dataclass(frozen=True)
class OrphanedOverride:
    rule_id: str
    severity: str
    source: str
    file: str


@dataclass(frozen=True)
class DisabledRule:
    rule: Rule
    severity_source: str


@dataclass(frozen=True)
class RuleListDetails:
    origins: dict[str, str]
    severity_sources: dict[str, str]
    drifted: set[str]
    orphaned_overrides: list[OrphanedOverride]
    disabled_rules: list[DisabledRule]
    definition_files: dict[str, str]
    definition_scopes: dict[str, str]


@dataclass(frozen=True)
class _Override:
    severity: Severity | None

    @property
    def label(self) -> str:
        return "off" if self.severity is None else self.severity.value


def user_overrides_file() -> Path:
    configured = os.environ.get("VARDE_CODE_USER_OVERRIDES_FILE") or os.environ.get(
        "VARDE_USER_OVERRIDES_FILE"
    )
    if configured:
        return Path(configured)
    config_dir = varde_config_dir() / "code"
    if (config_dir / ".varde-migration-complete").exists():
        return config_dir / "overrides.toml"
    legacy_dir = Path.home() / ".config" / "varde-code"
    return (legacy_dir if legacy_dir.exists() else config_dir) / "overrides.toml"


def load_overrides_file(path: Path) -> tuple[dict[str, _Override], list[Diagnostic]]:
    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, []
    except (OSError, UnicodeError) as error:
        return {}, [
            Diagnostic(None, str(path), f"unable to read overrides file: {error}")
        ]
    try:
        document = tomllib.loads(contents)
    except tomllib.TOMLDecodeError as error:
        return {}, [
            Diagnostic(None, str(path), f"invalid TOML overrides file: {error}")
        ]

    entries = document.get("rules")
    if not isinstance(entries, dict):
        if not document:
            return {}, []
        return {}, [Diagnostic(None, str(path), "expected a `[rules]` table")]

    overrides: dict[str, _Override] = {}
    diagnostics: list[Diagnostic] = []
    for rule_id, entry in entries.items():
        value = entry.get("severity") if isinstance(entry, dict) else None
        if not isinstance(value, str):
            diagnostics.append(
                Diagnostic(
                    rule_id, str(path), "override must include a string `severity`"
                )
            )
            continue
        if value.lower() == "off":
            overrides[rule_id] = _Override(None)
            continue
        severity = Severity.from_name(value)
        if severity is None:
            diagnostics.append(
                Diagnostic(
                    rule_id,
                    str(path),
                    f"invalid severity `{value}`; expected error, warning, info, or "
                    "off",
                )
            )
            continue
        overrides[rule_id] = _Override(severity)
    return overrides, diagnostics


def apply_overrides(
    rules: list[Rule],
    user: dict[str, _Override],
    repo: dict[str, _Override],
) -> tuple[list[Rule], dict[str, str], list[DisabledRule]]:
    active: list[Rule] = []
    applied: dict[str, str] = {}
    disabled: list[DisabledRule] = []
    for rule in rules:
        if rule.id not in repo and rule.id not in user:
            active.append(rule)
            continue
        source = "repo-override" if rule.id in repo else "user-override"
        override = repo[rule.id] if rule.id in repo else user[rule.id]
        applied[rule.id] = source
        if override.severity is None:
            disabled.append(DisabledRule(rule, source))
            continue
        active.append(replace(rule, severity=override.severity))
    return active, applied, disabled


def orphaned_overrides(
    known_rule_ids: set[str],
    user: dict[str, _Override],
    user_path: Path,
    repo: dict[str, _Override],
    repo_path: Path,
) -> list[OrphanedOverride]:
    results = [
        OrphanedOverride(rule_id, value.label, source, str(path))
        for source, path, overrides in (
            ("user-override", user_path, user),
            ("repo-override", repo_path, repo),
        )
        for rule_id, value in overrides.items()
        if rule_id not in known_rule_ids
    ]
    return sorted(results, key=lambda item: (item.rule_id, item.source, item.file))


def builtin_rule_pack_for(
    rule_id: str, builtin_packs: tuple[tuple[str, str], ...]
) -> tuple[str, str] | None:
    for label, contents in builtin_packs:
        tables = rule_tables(contents)
        if tables is not None and rule_id in tables:
            return label, contents
    return None


def seed_drifted(
    rule_id: str, file: str, builtin_packs: tuple[tuple[str, str], ...]
) -> bool:
    pack = builtin_rule_pack_for(rule_id, builtin_packs)
    if pack is None:
        return False
    label, contents = pack
    if Path(file).name != Path(label).name:
        return False
    try:
        seeded_contents = Path(file).read_text(encoding="utf-8")
    except OSError, UnicodeError:
        return False
    seeded = rule_tables(seeded_contents)
    builtin = rule_tables(contents)
    return (
        seeded is not None
        and builtin is not None
        and seeded.get(rule_id) != builtin.get(rule_id)
    )


def rule_tables(contents: str) -> dict[str, dict] | None:
    try:
        document = tomllib.loads(contents)
    except tomllib.TOMLDecodeError:
        return None
    entries = document.get("rule", [])
    if not isinstance(entries, list):
        return None
    return {
        entry["id"]: entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }


def seed_builtin_rules_for(
    target_dir: Path,
    builtin_packs: tuple[tuple[str, str], ...],
    *,
    force: bool = False,
    rule_id: str | None = None,
) -> list[SeedResult]:
    selected = (
        builtin_rule_pack_for(rule_id, builtin_packs) if rule_id is not None else None
    )
    if rule_id is not None and selected is None:
        raise ValueError(f"unknown built-in rule id: {rule_id}")
    packs = (selected,) if selected is not None else builtin_packs
    target_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for label, contents in packs:
        file_name = Path(label).name
        path = target_dir / file_name
        if path.exists() and not force:
            results.append(SeedResult(file_name, path, False, True))
            continue
        path.write_text(contents, encoding="utf-8")
        results.append(SeedResult(file_name, path, True, False))
    return results


def remove_builtin_rules(
    target_dir: Path, builtin_packs: tuple[tuple[str, str], ...], *, force: bool = False
) -> list[RemoveResult]:
    results = []
    for label, contents in builtin_packs:
        file_name = Path(label).name
        path = target_dir / file_name
        if not path.exists():
            continue
        try:
            on_disk = path.read_text(encoding="utf-8")
        except UnicodeError as error:
            raise OSError(
                f"invalid UTF-8 in seeded rules file {path}: {error}"
            ) from error
        if on_disk != contents and not force:
            results.append(RemoveResult(file_name, path, False, True))
            continue
        path.unlink()
        results.append(RemoveResult(file_name, path, True, False))
    return results
