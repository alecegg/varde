"""Preset setup for repository and user rule overrides."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, ClassVar

from varde_code.parse import language_for_path, language_from_name, language_name
from varde_code.query.modes import index_service
from varde_code.query.params import QueryError, req_str
from varde_code.rules import loader
from varde_code.rules.model import RuleKind
from varde_code.rules.overrides import user_overrides_file
from varde_code.rules.pattern import _walk_pattern_files
from varde_code.scan.rules_cmd import list_rules

PRESET_RULE_IDS = (
    "quality-file-floor",
    "quality-function-cap",
    "quality-scope-mean",
    "file-complexity-hotspot",
    "function-complexity-gate",
    "duplicate-code-clone",
    "debug-macro-strict",
    "debug-statement-strict",
    "low-fan-in-high-fan-out-file",
    "fat-interface",
    "too-many-interfaces",
    "deep-inheritance",
)
LENIENT_RULE_IDS = ("quality-file-floor", "quality-function-cap")


class Preset:
    NAMES: ClassVar[dict[str, str | None]] = {
        "minimal": "off",
        "balanced": None,
        "strict": "error",
        "lenient": "warning",
    }


def overrides_toml(
    preset: str,
    reason: str | None = None,
    date: str | None = None,
    review_by: str | None = None,
) -> str | None:
    severity = Preset.NAMES.get(preset, "unknown")
    if severity == "unknown":
        raise QueryError(
            "invalid_input",
            f"unknown preset {preset!r}; expected minimal, balanced, strict, "
            "or lenient",
        )
    if severity is None:
        return None
    if preset == "lenient":
        return _lenient_toml(reason, date, review_by)
    return "".join(
        f'[rules.{rule_id}]\nseverity = "{severity}"\n\n' for rule_id in PRESET_RULE_IDS
    )


def _lenient_toml(reason: str | None, date: str | None, review_by: str | None) -> str:
    """Lower the quality floor and cap to warning; a downgrade needs a reason."""
    if not reason or not reason.strip():
        raise QueryError(
            "invalid_input",
            "lenient lowers quality-file-floor and quality-function-cap to warning "
            "and requires a non-empty reason",
        )
    lines = [f"reason = {_toml_string(reason.strip())}"]
    for key, value in (("date", date), ("review_by", review_by)):
        if value:
            lines.append(f"{key} = {_toml_string(value)}")
    body = "\n".join(lines)
    return "".join(
        f'[rules.{rule_id}]\nseverity = "warning"\n{body}\n\n'
        for rule_id in LENIENT_RULE_IDS
    )


def _toml_string(value: str) -> str:
    return json.dumps(value)


def detect_languages(root: Path) -> list[str]:
    if not root.is_dir():
        raise QueryError("invalid_input", f"repoRoot is not a directory: {root}")
    service = index_service()
    if service is not None:
        db_path = Path(service.repo_db_path(root))
        if db_path.is_file():
            try:
                with sqlite3.connect(
                    f"file:{db_path.resolve()}?mode=ro", uri=True
                ) as db:
                    paths = [
                        row[0]
                        for row in db.execute("SELECT path FROM files ORDER BY path")
                    ]
                return _languages(paths)
            except sqlite3.Error as error:
                raise QueryError("db_error", str(error)) from error
    files = _walk_pattern_files(root)
    return _languages(files)


def filter_rules(rules: list[Any], languages: list[str]) -> list[Any]:
    detected = set(languages)
    result = []
    for rule in rules:
        if rule.kind is RuleKind.SQL or not rule.languages:
            result.append(rule)
            continue
        if any(
            (language := language_from_name(name.lower())) is not None
            and language_name(language) in detected
            for name in rule.languages
        ):
            result.append(rule)
    return result


def run(input: object) -> dict[str, Any]:
    if not isinstance(input, dict):
        raise QueryError("invalid_input", "input must be a JSON object")
    raw_root = req_str(input, "repoRoot")
    root = Path(raw_root)
    preset = input.get("preset")
    if not isinstance(preset, str):
        raise QueryError("invalid_input", "preset must be a string")
    overrides = overrides_toml(
        preset,
        _optional_str(input, "reason"),
        _optional_str(input, "date"),
        _optional_str(input, "review_by"),
    )
    scope = input.get("scope", "repo")
    if not isinstance(scope, str) or scope not in {"repo", "user"}:
        raise QueryError("invalid_input", "scope must be either repo or user")
    force = input.get("force", False)
    if not isinstance(force, bool):
        raise QueryError("invalid_input", "force must be a boolean")
    languages = detect_languages(root)
    written = None
    if overrides is not None:
        path = (
            _user_override_path()
            if scope == "user"
            else root / ".varde-code" / "overrides.toml"
        )
        _write_overrides(path, overrides, force)
        written = str(path)
    listing = list_rules(root)
    active_rules, _, details = loader.load_rules_with_details(root)
    effective_ids = {rule.id for rule in filter_rules(active_rules, languages)}
    disabled_rules = [item.rule for item in details.disabled_rules]
    disabled_ids = {rule.id for rule in filter_rules(disabled_rules, languages)}
    effective = [item for item in listing["rules"] if item["id"] in effective_ids]
    effective.extend(item for item in listing["rules"] if item["id"] in disabled_ids)
    return {
        "preset": preset,
        "scope": scope,
        "message": "Balanced leaves existing overrides unchanged; no overrides file "
        "was written."
        if preset == "balanced"
        else "Preset overrides were written.",
        "detectedLanguages": languages,
        "written": written,
        "effectiveRules": effective,
        "diagnostics": listing["diagnostics"],
        "orphanedOverrides": listing["orphanedOverrides"],
        "findings": [],
        "gate": {"status": "pass"},
    }


def _optional_str(input: dict[str, Any], key: str) -> str | None:
    value = input.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise QueryError("invalid_input", f"{key} must be a string")
    return value


def _languages(paths: list[str]) -> list[str]:
    return sorted(
        {
            language_name(language)
            for path in paths
            if (language := language_for_path(path)) is not None
        }
    )


def _user_override_path() -> Path:
    configured = os.environ.get("VARDE_CODE_USER_OVERRIDES_FILE") or os.environ.get(
        "VARDE_USER_OVERRIDES_FILE"
    )
    if configured:
        return Path(configured)
    return user_overrides_file()


def _write_overrides(path: Path, contents: str, force: bool) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise QueryError(
            "io_error", f"unable to create overrides directory {path.parent}: {error}"
        ) from error
    if not force:
        try:
            with path.open("x", encoding="utf-8") as file:
                file.write(contents)
        except FileExistsError as error:
            raise QueryError(
                "overwrite_refused", f"{path} already exists; pass --force to overwrite"
            ) from error
        except OSError as error:
            raise QueryError(
                "io_error", f"unable to write overrides file {path}: {error}"
            ) from error
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary = Path(file.name)
            file.write(contents)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    except OSError as error:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise QueryError(
            "io_error", f"unable to replace overrides file {path}: {error}"
        ) from error
