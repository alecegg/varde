"""Discover, parse, merge, and manage rule-pack files."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Never

from varde_core.paths import varde_config_dir

from varde_code.rules import overrides
from varde_code.rules.model import (
    Diagnostic,
    Rule,
    RuleKind,
    TestCase,
    Verification,
    boundary_configured,
)
from varde_code.rules.overrides import RemoveResult, RuleListDetails, SeedResult


def _raise_rule_validation_error(message: str) -> Never:
    raise ValueError(message)


@dataclass(frozen=True)
class DiscoveredFile:
    path: Path
    scope: str


@dataclass(frozen=True)
class LoadedRule:
    rule: Rule
    file: str


def user_rules_dir() -> Path:
    configured = os.environ.get("VARDE_CODE_USER_RULES_DIR") or os.environ.get(
        "VARDE_USER_RULES_DIR"
    )
    if configured:
        return Path(configured)
    config_dir = varde_config_dir() / "code"
    marker = config_dir / ".varde-migration-complete"
    if marker.exists():
        return config_dir / "rules"
    return Path.home() / ".config" / "varde-code" / "rules"


def discover(
    repo_root: Path, user_dir: Path | None = None
) -> tuple[list[DiscoveredFile], list[Diagnostic]]:
    files: list[DiscoveredFile] = []
    diagnostics: list[Diagnostic] = []
    if user_dir is not None:
        _collect(user_dir, "user", files, diagnostics)
    _collect(repo_root / ".varde-code" / "rules", "project", files, diagnostics)
    return files, diagnostics


def parse_pack_file(path: Path) -> tuple[list[Rule], list[Diagnostic]]:
    file = str(path)
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as error:
        return [], [Diagnostic(None, file, f"unreadable rule pack: {error}")]
    return _parse_pack(contents, file)


def load_rules(
    repo_root: Path, *, builtins: tuple[tuple[str, str], ...] | None = None
) -> tuple[list[Rule], list[Diagnostic]]:
    rules, diagnostics, _ = load_rules_with_details(repo_root, builtins=builtins)
    return rules, diagnostics


def load_rules_with_details(
    repo_root: Path, *, builtins: tuple[tuple[str, str], ...] | None = None
) -> tuple[list[Rule], list[Diagnostic], RuleListDetails]:
    builtin_packs = builtins if builtins is not None else _builtin_packs()
    builtin_loaded: list[LoadedRule] = []
    diagnostics: list[Diagnostic] = []
    for file, contents in builtin_packs:
        rules, issues = _parse_pack(contents, file)
        builtin_loaded.extend(LoadedRule(rule, file) for rule in rules)
        diagnostics.extend(issues)

    files, issues = discover(repo_root, user_rules_dir())
    diagnostics.extend(issues)
    user_loaded: list[LoadedRule] = []
    project_loaded: list[LoadedRule] = []
    for discovered in files:
        rules, issues = parse_pack_file(discovered.path)
        diagnostics.extend(issues)
        loaded = [LoadedRule(rule, str(discovered.path)) for rule in rules]
        (user_loaded if discovered.scope == "user" else project_loaded).extend(loaded)
    user_files = _first_rule_files(user_loaded)
    project_files = _first_rule_files(project_loaded)
    rules, issues = _merge(user_loaded, project_loaded)
    diagnostics.extend(issues)
    builtin_ids = {loaded.rule.id for loaded in builtin_loaded}
    origins = {
        rule.id: "override" if rule.id in builtin_ids else "custom" for rule in rules
    }
    severity_sources: dict[str, str] = {}
    definition_files: dict[str, str] = {}
    definition_scopes: dict[str, str] = {}
    for rule in rules:
        if rule.id in project_files:
            severity_sources[rule.id] = "repo-rule"
            definition_files[rule.id] = project_files[rule.id]
            definition_scopes[rule.id] = "repo"
        elif rule.id in user_files:
            severity_sources[rule.id] = "user-rule"
            definition_files[rule.id] = user_files[rule.id]
            definition_scopes[rule.id] = "user"
    present = {rule.id for rule in rules}
    for loaded in builtin_loaded:
        if loaded.rule.id not in present:
            rules.append(loaded.rule)
            present.add(loaded.rule.id)
            origins[loaded.rule.id] = "builtin"
            severity_sources[loaded.rule.id] = "builtin"

    user_override_path = overrides.user_overrides_file()
    repo_override_path = repo_root / ".varde-code" / "overrides.toml"
    user_overrides, issues = overrides.load_overrides_file(user_override_path)
    diagnostics.extend(issues)
    repo_overrides, issues = overrides.load_overrides_file(repo_override_path)
    diagnostics.extend(issues)
    known_rule_ids = {rule.id for rule in rules}
    orphaned = overrides.orphaned_overrides(
        known_rule_ids,
        user_overrides,
        user_override_path,
        repo_overrides,
        repo_override_path,
    )
    rules, applied, disabled = overrides.apply_overrides(
        rules, user_overrides, repo_overrides
    )
    for rule_id, source in applied.items():
        origins[rule_id] = "override"
        severity_sources[rule_id] = source
    active_ids = {rule.id for rule in rules}
    origins = {
        rule_id: origin for rule_id, origin in origins.items() if rule_id in active_ids
    }
    severity_sources = {
        rule_id: source
        for rule_id, source in severity_sources.items()
        if rule_id in active_ids
    }
    drifted = {
        rule_id
        for rule_id, file in definition_files.items()
        if overrides.seed_drifted(rule_id, file, builtin_packs)
    }
    return (
        rules,
        diagnostics,
        RuleListDetails(
            origins,
            severity_sources,
            drifted,
            orphaned,
            disabled,
            definition_files,
            definition_scopes,
        ),
    )


def seed_builtin_rules(target_dir: Path, *, force: bool = False) -> list[SeedResult]:
    return seed_builtin_rules_for(target_dir, force=force)


def seed_builtin_rules_for(
    target_dir: Path, *, force: bool = False, rule_id: str | None = None
) -> list[SeedResult]:
    return overrides.seed_builtin_rules_for(
        target_dir, _builtin_packs(), force=force, rule_id=rule_id
    )


def builtin_rule_pack_for(rule_id: str) -> tuple[str, str] | None:
    return overrides.builtin_rule_pack_for(rule_id, _builtin_packs())


def builtin_rules() -> list[Rule]:
    rules: list[Rule] = []
    for file, contents in _builtin_packs():
        pack_rules, _ = _parse_pack(contents, file)
        rules.extend(pack_rules)
    return rules


def seed_drifted(rule_id: str, file: str) -> bool:
    return overrides.seed_drifted(rule_id, file, _builtin_packs())


def remove_builtin_rules(
    target_dir: Path, *, force: bool = False
) -> list[RemoveResult]:
    return overrides.remove_builtin_rules(target_dir, _builtin_packs(), force=force)


def _first_rule_files(loaded: list[LoadedRule]) -> dict[str, str]:
    files: dict[str, str] = {}
    for item in loaded:
        files.setdefault(item.rule.id, item.file)
    return files


def list_rule_packs(
    repo_root: Path, user_dir: Path | None = None
) -> tuple[list[DiscoveredFile], list[Diagnostic]]:
    """List user and project pack files in deterministic scope/path order."""
    return discover(repo_root, user_rules_dir() if user_dir is None else user_dir)


def _collect(
    directory: Path,
    scope: str,
    files: list[DiscoveredFile],
    diagnostics: list[Diagnostic],
) -> None:
    try:
        paths = sorted(directory.iterdir())
    except FileNotFoundError:
        return
    except OSError as error:
        if directory.exists():
            diagnostics.append(
                Diagnostic(None, str(directory), f"unreadable rule directory: {error}")
            )
        return
    for path in paths:
        try:
            if path.is_file() and path.suffix == ".toml":
                files.append(DiscoveredFile(path, scope))
        except OSError as error:
            diagnostics.append(
                Diagnostic(
                    None, str(directory), f"unreadable rule directory entry: {error}"
                )
            )


def _parse_pack(contents: str, file: str) -> tuple[list[Rule], list[Diagnostic]]:
    try:
        document = tomllib.loads(contents)
    except tomllib.TOMLDecodeError as error:
        return [], [Diagnostic(None, file, f"invalid TOML: {error}")]
    entries = document.get("rule", [])
    if not isinstance(entries, list):
        return [], []
    rules: list[Rule] = []
    diagnostics: list[Diagnostic] = []
    for entry in entries:
        rule_id = entry.get("id") if isinstance(entry, dict) else None
        try:
            if not isinstance(entry, dict):
                _raise_rule_validation_error("rule entry must be a table")
            rule = Rule.from_mapping(entry)
            _validate_kind_fields(rule)
            test_cases, test_diagnostics = _parse_test_entries(entry, rule, file)
            diagnostics.extend(test_diagnostics)
            rule = replace(rule, test=test_cases or None)
            rules.append(rule)
        except (TypeError, ValueError) as error:
            diagnostics.append(
                Diagnostic(
                    rule_id if isinstance(rule_id, str) else None, file, str(error)
                )
            )
    return rules, diagnostics


def _merge(
    user: list[LoadedRule], project: list[LoadedRule]
) -> tuple[list[Rule], list[Diagnostic]]:
    rules: list[Rule] = []
    positions: dict[str, int] = {}
    owners: dict[str, str] = {}
    diagnostics: list[Diagnostic] = []
    user_owned: set[str] = set()
    for scope_name, loaded_rules in (("user", user), ("project", project)):
        for loaded in loaded_rules:
            rule_id = loaded.rule.id
            if rule_id not in positions:
                positions[rule_id] = len(rules)
                owners[rule_id] = scope_name
                rules.append(loaded.rule)
                if scope_name == "user":
                    user_owned.add(rule_id)
            elif scope_name == "project" and rule_id in user_owned:
                user_owned.remove(rule_id)
                rules[positions[rule_id]] = loaded.rule
                owners[rule_id] = scope_name
            else:
                label = "repo" if scope_name == "project" else scope_name
                diagnostics.append(
                    Diagnostic(
                        rule_id,
                        loaded.file,
                        (
                            f"duplicate rule id `{rule_id}` in {label} scope; "
                            "first-loaded rule kept"
                        ),
                    )
                )
    return rules, diagnostics


def _builtin_packs() -> tuple[tuple[str, str], ...]:
    directory = Path(__file__).parent / "builtin"
    if not directory.is_dir():
        return ()
    return tuple(
        (f"<builtin>/{name}", (directory / name).read_text(encoding="utf-8"))
        for name in BUILTIN_PACK_NAMES
        if (directory / name).is_file()
    )


BUILTIN_PACK_NAMES = (
    "quality_gate.toml",
    "complexity.toml",
    "empty_catch_block.toml",
    "eval_usage.toml",
    "duplicate_code_clone.toml",
    "debug_statement_strict.toml",
    "hardcoded_credential_literal.toml",
    "low_fan_in_high_fan_out_file.toml",
    "circular_import.toml",
    "unresolved_local_import.toml",
    "vertical_slice_sprawl.toml",
    "solid.toml",
    "dependency_boundary.toml",
    "hardcoded_credential_rust.toml",
    "hardcoded_credential_go.toml",
    "hardcoded_credential_jvm_dotnet.toml",
    "hardcoded_credential_native_apple.toml",
    "hardcoded_credential_native_apple_class.toml",
    "hardcoded_credential_scripting.toml",
    "hardcoded_credential_other.toml",
    "error_swallow_rust.toml",
    "error_swallow_go.toml",
    "error_swallow_c_scala_solidity.toml",
    "error_swallow_lua_bash.toml",
    "error_swallow_elixir_haskell.toml",
)


def _validate_kind_fields(rule: Rule) -> None:
    if rule.verification is not None:
        if rule.kind is not RuleKind.SQL:
            raise ValueError("verification is only supported on kind=sql rules")
        if rule.verification is Verification.EXACT_CLONE:
            from varde_code.rules.clone_verification import thresholds

            thresholds(rule)
        if rule.verification is Verification.DEPENDENCY_BOUNDARY:
            configured = boundary_configured(rule)
            if isinstance(configured, str):
                raise ValueError(configured)
    if rule.kind is RuleKind.PATTERN:
        if rule.pattern is None:
            raise ValueError("rule kind=pattern requires a `pattern` field")
        if rule.rewrite is not None:
            from varde_code.rules.pattern import validate_rewrite_template

            validate_rewrite_template(rule.rewrite, rule.pattern)
    elif rule.query is None:
        raise ValueError("rule kind=sql requires a `query` field")
    elif rule.rewrite is not None:
        raise ValueError(
            "rewrite is only supported on kind=pattern rules "
            "(SQL findings are not anchored to a single source span)"
        )


def _parse_test_entries(
    entry: dict, rule: Rule, file: str
) -> tuple[list[TestCase], list[Diagnostic]]:
    raw_cases = entry.get("test")
    if not isinstance(raw_cases, list):
        return [], []
    cases: list[TestCase] = []
    diagnostics: list[Diagnostic] = []
    for raw in raw_cases:
        try:
            if not isinstance(raw, dict):
                _raise_rule_validation_error("expected a table")
            name = raw.get("name")
            if not isinstance(name, str):
                _raise_rule_validation_error(
                    "missing field `name`"
                    if "name" not in raw
                    else "invalid type: expected string for `name`"
                )
            for key in ("valid", "invalid"):
                if raw.get(key) is not None and (
                    not isinstance(raw[key], list)
                    or any(not isinstance(item, str) for item in raw[key])
                ):
                    _raise_rule_validation_error(
                        f"invalid type: expected an array of strings for `{key}`"
                    )
            for key in ("expect_rewrite", "fixture"):
                item = raw.get(key)
                if item is not None and (
                    not isinstance(item, dict)
                    or any(
                        not isinstance(k, str) or not isinstance(v, str)
                        for k, v in item.items()
                    )
                ):
                    _raise_rule_validation_error(
                        f"invalid type: expected a map of strings for `{key}`"
                    )
            rows = raw.get("expect_rows")
            if rows is not None and (
                not isinstance(rows, list)
                or any(not isinstance(row, dict) for row in rows)
            ):
                _raise_rule_validation_error(
                    "invalid type: expected an array of tables for `expect_rows`"
                )
            case = TestCase(
                name,
                raw.get("valid"),
                raw.get("invalid"),
                raw.get("expect_rewrite"),
                raw.get("fixture"),
                rows,
            )
            if rule.kind is RuleKind.PATTERN:
                if case.fixture is not None:
                    _raise_rule_validation_error(
                        f"test `{name}`: `fixture` is only valid on kind=sql rules"
                    )
                if case.expect_rows is not None:
                    _raise_rule_validation_error(
                        f"test `{name}`: `expect_rows` is only valid on kind=sql rules"
                    )
                if case.expect_rewrite is not None and rule.rewrite is None:
                    _raise_rule_validation_error(
                        f"test `{name}`: `expect_rewrite` requires the rule to "
                        "define `rewrite`"
                    )
            else:
                for key in ("valid", "invalid", "expect_rewrite"):
                    if getattr(case, key) is not None:
                        _raise_rule_validation_error(
                            f"test `{name}`: `{key}` is only valid on "
                            "kind=pattern rules"
                        )
            cases.append(case)
        except (TypeError, ValueError) as error:
            reason = str(error)
            if not reason.startswith("test `"):
                reason = f"malformed [[test]] entry: {reason}"
            diagnostics.append(Diagnostic(rule.id, file, reason))
    return cases, diagnostics
