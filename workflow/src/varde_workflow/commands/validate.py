"""Artifact validation command behavior."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from varde_core.text_audit import Finding, Rule, Severity, audit

from varde_workflow.artifact import (
    ArtifactEnvelope,
    ArtifactInvalid,
    Diagnostic,
    inspect,
)
from varde_workflow.commands.status import parse_status_at, status_bucket
from varde_workflow.execution_wave import ownership_declarations, serial_plan
from varde_workflow.output import print_cli_failure_with_meta, print_cli_success
from varde_workflow.plan_labels import (
    label_findings,
    resolve_group,
    resolve_parent_group,
)
from varde_workflow.review_structure import review_structure
from varde_workflow.schema import built_in
from varde_workflow.task_ownership import resolve as resolve_ownership

PLAN_STATUSES = {"active", "backlog", "blocked", "cancelled", "completed"}
LEGACY_PLAN_STATUSES = {"archived", "complete", "dismissed", "stale"}
TASK_STATUSES = built_in().artifact_type("task").states
TASK_KEYS = {
    "artifact_type",
    "creates",
    "depends_on",
    "generated",
    "id",
    "kind",
    "modifies",
    "owns",
    "posture",
    "provenance",
    "risk",
    "relationships",
    "renames",
    "schema_version",
    "status",
    "status_at",
    "title",
    "type",
    "verification_resources",
}


def resolve_target(path: Path | str) -> Path:
    target = Path(path)
    if not target.is_dir():
        return target
    for name in ("plan.md", "task.md"):
        candidate = target / name
        if candidate.is_file():
            return candidate
    raise ArtifactInvalid(
        [Diagnostic("document", f"{target} has no plan.md or task.md")]
    )


def validate(
    path: Path | str,
) -> tuple[ArtifactEnvelope | None, list[Diagnostic], list[Finding]]:
    try:
        target = resolve_target(path)
        envelope = inspect(target)
    except ArtifactInvalid as exc:
        return None, exc.diagnostics, []
    errors, warnings = text_findings(envelope, target)
    if envelope.artifact_type == "plan":
        try:
            frontmatter, _ = _parse(target)
        except OSError, ValueError:
            frontmatter = {}
        resolved_group = _resolved_group(target, frontmatter)
        warnings.extend(
            Finding(str(target), 1, Rule.LAYOUT, Severity.WARN, message)
            for message in label_findings(
                frontmatter.get("label"),
                resolved_group,
                frontmatter.get("title"),
                str(frontmatter.get("id") or target.parent.name),
                _other_open_labels(target),
            )
        )
        errors.extend(status_and_key_findings(target, envelope))
        if envelope.status != "cancelled":
            errors.extend(ownership_findings(target))
    else:
        errors.extend(status_and_key_findings(target, envelope))
        if envelope.artifact_type == "review":
            errors.extend(
                Diagnostic("review", message)
                for message in review_structure(target, repo=Path.cwd())
            )
    return (envelope if not errors else None), errors, warnings


def _other_open_labels(plan: Path) -> set[str]:
    plans_dirs = [directory for directory in plan.parents if directory.name == "plans"]
    plans_dir = plans_dirs[-1] if plans_dirs else None
    if plans_dir is None or plan.parent == plans_dir:
        return set()
    labels = set()
    for sibling_plan in plans_dir.rglob("plan.md"):
        if sibling_plan == plan:
            continue
        try:
            frontmatter, _ = _parse(sibling_plan)
        except OSError, ValueError:
            continue
        status = frontmatter.get("status")
        if isinstance(status, str) and status_bucket(status) == "terminal":
            continue
        label = frontmatter.get("label")
        if isinstance(label, str) and label.strip():
            labels.add(label)
    return labels


def _resolved_group(plan: Path, frontmatter: dict[str, Any]) -> str:
    plans_dir = next(
        (directory for directory in plan.parents if directory.name == "plans"), None
    )
    if plans_dir is None:
        return resolve_group(frontmatter.get("group"), "")
    ancestors = []
    directory = plan.parent.parent
    while directory.is_relative_to(plans_dir):
        ancestor_plan = directory / "plan.md"
        if ancestor_plan.is_file():
            try:
                ancestor, _ = _parse(ancestor_plan)
            except OSError, ValueError:
                ancestor = {}
            ancestors.append(ancestor.get("group"))
        if directory == plans_dir:
            break
        directory = directory.parent
    return resolve_group(frontmatter.get("group"), resolve_parent_group(ancestors))


def run(args: Any) -> int:
    envelope, errors, warnings = validate(args.artifact)
    if envelope is not None:
        data = {"artifact": envelope.to_json(), "diagnostics": [], "valid": True}
        if envelope.artifact_type == "plan" and warnings:
            data["text_warnings"] = [
                {
                    "line": item.line,
                    "message": item.message,
                    "path": item.path,
                    "rule": item.rule.value,
                    "severity": item.severity.value,
                }
                for item in warnings
            ]
        if args.json:
            print_cli_success(data)
        else:
            print(f"valid: {args.artifact}")
            for warning in warnings:
                print(f"warn: {warning.path}:{warning.line} {warning.message}")
        return 0
    if args.json:
        print_cli_failure_with_meta(
            "validation_failed",
            "artifact validation failed",
            [item.to_json() for item in errors],
            {"truncated": False},
        )
    else:
        for error in errors:
            print(f"{error.field}: {error.message}", file=sys.stderr)
        for warning in warnings:
            print(
                f"warn: {warning.path}:{warning.line} {warning.message}",
                file=sys.stderr,
            )
    return 4


def ownership_findings(plan: Path) -> list[Diagnostic]:
    plan_dir = plan.parent
    try:
        tasks = ownership_declarations(plan_dir)
    except (OSError, ValueError, TypeError) as error:
        return [Diagnostic("ownership", str(error))]
    if not any(
        paths.owned or paths.owns or paths.creates or paths.generated
        for _, _, paths in tasks
    ):
        return []
    root = _repository_root(Path.cwd()) or _repository_root(plan_dir)
    if root is None:
        return [
            Diagnostic(
                "ownership", "cannot discover repository root for task ownership"
            )
        ]
    permitted_missing = {
        declaration
        for _, status, paths in tasks
        for declaration in paths.owned | paths.creates
        if status == "done" or declaration in paths.creates
    }
    diagnostics = []
    for task_id, _, declarations in tasks:
        result = resolve_ownership(root, declarations, [], None, permitted_missing)
        diagnostics.extend(
            Diagnostic(f"tasks.{task_id}.ownership", message)
            for message in result.blockers
        )
    return diagnostics


def _repository_root(path: Path) -> Path | None:
    try:
        result = subprocess.run(  # noqa: S603 - Reads repository metadata using fixed Git argv.
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],  # noqa: S607 - Git is the required repository executable from PATH.
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode or not result.stdout.strip():
        return None
    return Path(result.stdout.strip())


def text_findings(
    envelope: ArtifactEnvelope, path: Path
) -> tuple[list[Diagnostic], list[Finding]]:
    if envelope.artifact_type not in {"plan", "task"}:
        return [], []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [], []
    findings = audit(blank_progress(text), str(path))
    findings.extend(
        _inline_list_findings(text, str(path), {item.line for item in findings})
    )
    errors = [item for item in findings if item.severity == Severity.ERROR]
    warnings = [item for item in findings if item.severity != Severity.ERROR]
    warnings.sort(key=lambda item: item.line)
    return [
        Diagnostic("text", f"{item.path}:{item.line} {item.message}") for item in errors
    ], warnings


def _inline_list_findings(
    text: str, path: str, existing_lines: set[int]
) -> list[Finding]:
    findings = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if line_number in existing_lines:
            continue
        plain = re.sub(r"`[^`]*`", "", line)
        conjunction = re.search(r"\b(?:and|or)\b", plain)
        if conjunction is None:
            continue
        if plain.rfind("(", 0, conjunction.start()) > plain.rfind(
            ")", 0, conjunction.start()
        ):
            continue
        series = plain[: conjunction.start()].rsplit(";", 1)[-1]
        if "," not in series:
            continue
        count = series.count(",") + 2
        findings.append(
            Finding(
                path,
                line_number,
                Rule.INLINE_LIST,
                Severity.WARN,
                f"(inline list, {count} items); put one item per line under a lead-in",
            )
        )
    return findings


def blank_progress(text: str) -> str:
    progress_level = None
    fence: tuple[str, int] | None = None
    output: list[str] = []
    for line in text.splitlines():
        marker = _fence_marker(line)
        if fence is not None:
            if (
                marker is not None
                and marker[0] == fence[0]
                and marker[1] >= fence[1]
                and marker[2]
            ):
                fence = None
            output.append("" if progress_level is not None and marker is None else line)
        elif marker is not None:
            fence = marker[:2]
            output.append(line)
        else:
            heading = _heading(line)
            if heading is not None:
                level, title = heading
                if progress_level is None or level <= progress_level:
                    progress_level = (
                        level if title == "Progress" and level <= 4 else None
                    )
            output.append("" if progress_level is not None else line)
    return "\n".join(output)


def _fence_marker(line: str) -> tuple[str, int, bool] | None:
    trimmed = line.lstrip()
    if not trimmed or trimmed[0] not in "`~":
        return None
    marker = trimmed[0]
    length = len(trimmed) - len(trimmed.lstrip(marker))
    return (marker, length, not trimmed[length:].strip()) if length >= 3 else None


def _heading(line: str) -> tuple[int, str] | None:
    level = len(line) - len(line.lstrip("#"))
    if level < 2 or level == len(line) or line[level] != " ":
        return None
    return level, line[level:].strip()


def _scope_diagnostics(path: Path, frontmatter: dict[str, Any]) -> list[Diagnostic]:
    scope = frontmatter.get("scope")
    if scope is None:
        return []
    if not isinstance(scope, list) or any(
        not isinstance(item, str) or not item.strip() for item in scope
    ):
        return [Diagnostic("scope", "field must be a list of non-empty strings")]
    tasks = path.parent / "tasks"
    if not tasks.is_dir() or not any(tasks.glob("*.md")) or serial_plan(path.parent):
        return []
    return [
        Diagnostic(
            "scope",
            "field applies only to serial plans (tasks in one depends_on chain)",
        )
    ]


def status_and_key_findings(path: Path, envelope: ArtifactEnvelope) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    mappings: list[tuple[dict[str, Any], str]] = []
    try:
        frontmatter, _ = _parse(path)
    except OSError, ValueError:
        return diagnostics
    mappings.append((frontmatter, ""))
    if envelope.artifact_type == "plan":
        gate = frontmatter.get("gate")
        if gate is not None and (
            not isinstance(gate, list)
            or any(not isinstance(item, str) for item in gate)
        ):
            diagnostics.append(Diagnostic("gate", "field must be a list of strings"))
        diagnostics.extend(_scope_diagnostics(path, frontmatter))
        branches = frontmatter.get("branches")
        if branches is not None and (
            not isinstance(branches, list)
            or any(not isinstance(item, str) or not item.strip() for item in branches)
        ):
            diagnostics.append(
                Diagnostic("branches", "field must be a list of non-empty strings")
            )
    if envelope.artifact_type == "plan":
        tasks_dir = path.parent / "tasks"
        if tasks_dir.is_dir():
            for task_path in sorted(tasks_dir.glob("*.md")):
                try:
                    task_frontmatter, _ = _parse(task_path)
                except OSError, ValueError:
                    continue
                mappings.append((task_frontmatter, f"tasks.{task_path.stem}"))
    for mapping, prefix in mappings:
        artifact_type = (
            envelope.artifact_type
            if not prefix
            else mapping.get("artifact_type", mapping.get("type", "document"))
        )
        if artifact_type == "plan":
            legal = PLAN_STATUSES
        elif artifact_type == "task":
            legal = TASK_STATUSES
        else:
            continue
        status = mapping.get("status")
        if (
            status is not None
            and status not in legal
            and not (artifact_type == "plan" and status in LEGACY_PLAN_STATUSES)
        ):
            diagnostics.append(
                Diagnostic(
                    _field(prefix, "status"),
                    (
                        f"`{status}` is not a legal {artifact_type} status "
                        f"({', '.join(sorted(legal))})"
                    ),
                )
            )
        if artifact_type == "task":
            risk = mapping.get("risk")
            if risk is not None and risk != "high":
                diagnostics.append(
                    Diagnostic(_field(prefix, "risk"), "field must be `high` when set")
                )
            status_at = mapping.get("status_at")
            if status_at is not None and (
                not isinstance(status_at, str) or parse_status_at(status_at) is None
            ):
                diagnostics.append(
                    Diagnostic(
                        _field(prefix, "status_at"), "field must be an ISO timestamp"
                    )
                )
            diagnostics.extend(
                Diagnostic(_field(prefix, key), "unknown task frontmatter key")
                for key in mapping
                if isinstance(key, str) and key not in TASK_KEYS
            )
    return diagnostics


def _parse(path: Path) -> tuple[dict[str, Any], str]:
    from varde_learn.knowledge.frontmatter import parse

    return parse(path.read_bytes())


def _field(prefix: str, name: str) -> str:
    return f"{prefix}.{name}" if prefix else name
