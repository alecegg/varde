"""Rule-pack data types shared by rule loading and execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RuleKind(StrEnum):
    PATTERN = "pattern"
    SQL = "sql"


class Verification(StrEnum):
    EXACT_CLONE = "exact-clone"
    DEPENDENCY_FACTS = "dependency-facts"
    DEPENDENCY_BOUNDARY = "dependency-boundary"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @classmethod
    def from_name(cls, name: str) -> Severity | None:
        try:
            return cls(name.lower())
        except ValueError:
            return None

    @property
    def rank(self) -> int:
        return {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2}[self]


@dataclass(frozen=True)
class ConstraintSpec:
    """One regex constraint or an AND-list of regex constraints."""

    patterns: tuple[str, ...]

    @classmethod
    def parse(cls, value: str | list[str]) -> ConstraintSpec:
        if isinstance(value, str):
            return cls((value,))
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return cls(tuple(value))
        raise ValueError("constraint must be a string or an array of strings")


@dataclass(frozen=True)
class TestCase:
    name: str
    valid: list[str] | None = None
    invalid: list[str] | None = None
    expect_rewrite: dict[str, str] | None = None
    fixture: dict[str, str] | None = None
    expect_rows: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class Rule:
    id: str
    kind: RuleKind
    severity: Severity
    message: str
    verification: Verification | None = None
    name: str | None = None
    description: str | None = None
    remediation: str | None = None
    pattern: str | None = None
    query: str | None = None
    thresholds: dict[str, float] | None = None
    strings: dict[str, str] | None = None
    constraints: dict[str, ConstraintSpec] | None = None
    fix: str | None = None
    rewrite: str | None = None
    languages: list[str] | None = None
    exclude_test_paths: bool | None = None
    exclude_tooling_paths: bool | None = None
    test: list[TestCase] | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Rule:
        required = ("id", "kind", "severity", "message")
        for key in required:
            if key not in value:
                raise ValueError(f"missing field `{key}`")
        _require_type(value, "id", str)
        _require_type(value, "kind", str)
        _require_type(value, "severity", str)
        _require_type(value, "message", str)
        try:
            kind = RuleKind(value["kind"])
        except ValueError as error:
            raise ValueError(
                f"unknown variant `{value['kind']}`, expected `pattern` or `sql`"
            ) from error
        thresholds = value.get("thresholds")
        if thresholds is not None:
            if not isinstance(thresholds, dict) or any(
                not isinstance(key, str)
                or isinstance(item, bool)
                or not isinstance(item, (int, float))
                for key, item in thresholds.items()
            ):
                raise ValueError(
                    "invalid type: expected a map with string keys and numeric "
                    "values for `thresholds`"
                )
            thresholds = {key: float(item) for key, item in thresholds.items()}
        raw_constraints = value.get("constraints")
        constraints = None
        if raw_constraints is not None:
            if not isinstance(raw_constraints, dict) or any(
                not isinstance(key, str) for key in raw_constraints
            ):
                raise ValueError("invalid type: expected a map for `constraints`")
            constraints = {
                key: ConstraintSpec.parse(spec) for key, spec in raw_constraints.items()
            }
        for field_name in (
            "name",
            "description",
            "remediation",
            "pattern",
            "query",
            "fix",
            "rewrite",
        ):
            _require_optional_type(value, field_name, str)
        for field_name in ("strings",):
            mapping = value.get(field_name)
            if mapping is not None and (
                not isinstance(mapping, dict)
                or any(
                    not isinstance(key, str) or not isinstance(item, str)
                    for key, item in mapping.items()
                )
            ):
                raise ValueError(
                    f"invalid type: expected a map of strings for `{field_name}`"
                )
        languages = value.get("languages")
        if languages is not None and (
            not isinstance(languages, list)
            or any(not isinstance(item, str) for item in languages)
        ):
            raise ValueError(
                "invalid type: expected an array of strings for `languages`"
            )
        for field_name in ("exclude_test_paths", "exclude_tooling_paths"):
            item = value.get(field_name)
            if item is not None and not isinstance(item, bool):
                raise ValueError(f"invalid type: expected a boolean for `{field_name}`")
        return cls(
            id=value["id"],
            kind=kind,
            severity=Severity.from_name(str(value["severity"]))
            or _bad_severity(value["severity"]),
            message=value["message"],
            verification=Verification(value["verification"])
            if value.get("verification")
            else None,
            name=value.get("name"),
            description=value.get("description"),
            remediation=value.get("remediation"),
            pattern=value.get("pattern"),
            query=value.get("query"),
            thresholds=thresholds,
            strings=value.get("strings"),
            constraints=constraints,
            fix=value.get("fix"),
            rewrite=value.get("rewrite"),
            languages=value.get("languages"),
            exclude_test_paths=value.get("exclude_test_paths"),
            exclude_tooling_paths=value.get("exclude_tooling_paths"),
        )


def _require_type(value: dict[str, Any], key: str, expected: type) -> None:
    if not isinstance(value[key], expected):
        raise ValueError(f"invalid type: expected {expected.__name__} for `{key}`")


def _require_optional_type(value: dict[str, Any], key: str, expected: type) -> None:
    item = value.get(key)
    if item is not None and not isinstance(item, expected):
        raise ValueError(f"invalid type: expected {expected.__name__} for `{key}`")


def boundary_configured(rule: Rule) -> bool | str:
    if rule.verification is not Verification.DEPENDENCY_BOUNDARY:
        return True
    strings = rule.strings or {}
    source, target = strings.get("source_prefix", ""), strings.get("target_prefix", "")
    if not source and not target:
        return False
    for key, value in (("source_prefix", source), ("target_prefix", target)):
        if value == ".":
            continue
        if (
            not value
            or value.strip() != value
            or "\\" in value
            or any(part in ("", ".", "..") for part in value.split("/"))
        ):
            return (
                f"{key} must be a normalized relative directory or '.'; "
                "configure both prefixes"
            )
    return True


def _bad_severity(value: Any) -> Severity:
    raise ValueError(f"unknown severity: {value!r}")


@dataclass(frozen=True)
class Diagnostic:
    rule_id: str | None
    file: str
    reason: str
