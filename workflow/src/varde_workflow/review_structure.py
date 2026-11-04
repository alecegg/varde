"""Shared parsing for review findings and their literal fields."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from varde_learn.knowledge.frontmatter import parse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewFinding:
    id: str
    heading: str
    text: str
    severity: str | None
    status: str | None


def parse_findings(body: str) -> list[ReviewFinding]:
    headings = list(re.finditer(r"^## .+$", body, re.MULTILINE))
    findings = []
    for index, heading in enumerate(headings):
        finding = re.fullmatch(r"## \[([^]]+)\] .+", heading.group(0))
        if finding is None:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        text = body[heading.end() : end]
        severity = re.search(r"^\*\*Severity:\*\*\s*(.*?)\s*$", text, re.MULTILINE)
        status = re.search(r"^\*\*Status:\*\*\s*(.*?)\s*$", text, re.MULTILINE)
        findings.append(
            ReviewFinding(
                finding.group(1),
                heading.group(0),
                text,
                severity.group(1) if severity else None,
                status.group(1) if status else None,
            )
        )
    return findings


def review_structure(
    path: Path | str, *, full: bool = True, repo: Path | str | None = None
) -> list[str]:
    review = Path(path)
    try:
        mapping, body = parse(review.read_bytes())
    except (OSError, ValueError) as error:
        return [f"{review}: {error}"]
    errors = [
        f"review header is missing {key}"
        for key in ("verdict", "head")
        if not isinstance(mapping.get(key), str) or not mapping[key].strip()
    ]
    if not full:
        return errors
    ids: set[str] = set()
    findings = parse_findings(body)
    for finding in findings:
        if finding.id in ids:
            errors.append(f"duplicate finding id {finding.id}")
        ids.add(finding.id)
        severity = finding.severity
        if severity not in {"critical", "high", "medium", "low", "info"}:
            errors.append(f"{finding.id} has an invalid severity")
        if finding.status is None:
            errors.append(f"{finding.id} is missing Status")
        if "### Solutions" not in finding.text:
            errors.append(f"{finding.id} is missing ### Solutions")
        if (
            severity == "high"
            and finding.status is not None
            and finding.status.startswith("fixed")
            and not finding.id.startswith(("SPEC-", "GATE-"))
            and not _has_fix_commit(mapping, review, finding.id, repo)
        ):
            errors.append(
                f"{finding.id} is fixed high without a matching "
                f"fix({finding.id}) commit"
            )
    errors.extend(_review_history_findings(review, mapping, body, repo))
    return errors


def open_critical_or_high(path: Path | str) -> list[str]:
    try:
        _, body = parse(Path(path).read_bytes())
    except OSError, ValueError:
        return []
    matches = []
    known_severities = {"critical", "high", "medium", "low", "info"}
    closed_status = re.compile(r"^(fixed|waived|deferred|dismissed)(?:\s|$)")
    for finding in parse_findings(body):
        severity_parts = (finding.severity or "").split(None, 1)
        severity = severity_parts[0].casefold() if severity_parts else ""
        known_severity = severity in known_severities
        status = (finding.status or "").casefold()
        if (
            severity in {"critical", "high"}
            and not closed_status.match(status)
            or not known_severity
        ):
            matches.append(finding.id)
    return matches


def _review_history_findings(
    review: Path, mapping: dict[str, object], body: str, repo: Path | str | None
) -> list[str]:
    previous = _previous_review(review)
    if previous is None:
        return []
    previous_mapping, previous_body = previous
    current_findings = _finding_text(parse_findings(body))
    prior_findings = _finding_text(parse_findings(previous_body))
    changed = sorted(
        finding_id
        for finding_id in current_findings.keys() & prior_findings.keys()
        if current_findings[finding_id] != prior_findings[finding_id]
    )
    errors = [
        f"{finding_id} finding text changed since the prior head"
        for finding_id in changed
    ]
    if "## Re-check" not in body:
        return errors
    old_head, new_head = previous_mapping.get("head"), mapping.get("head")
    if not isinstance(old_head, str) or not isinstance(new_head, str):
        return errors
    repository = _repository_for_range(review, old_head, new_head, repo)
    if repository is None:
        logger.warning(
            "cannot check review re-check history: base/head commits are unavailable"
        )
        return errors
    if old_head == new_head:
        return errors
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "log",
            "--format=%s",
            f"{old_head}..{new_head}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    subjects = result.stdout.splitlines()
    if result.returncode or any(
        not re.match(r"^fix\([^)]+\):", subject) for subject in subjects
    ):
        errors.append(
            "header-only re-check includes commits other than fix(<ID>) commits"
        )
    return errors


def _previous_review(path: Path) -> tuple[dict[str, object], str] | None:
    root_result = subprocess.run(
        ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if root_result.returncode or not root_result.stdout.strip():
        return None
    root = Path(root_result.stdout.strip())
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    history = subprocess.run(
        ["git", "-C", str(root), "log", "--format=%H", "-2", "--", relative],
        capture_output=True,
        text=True,
        check=False,
    )
    for revision in history.stdout.splitlines():
        result = subprocess.run(
            ["git", "-C", str(root), "show", f"{revision}:{relative}"],
            capture_output=True,
            check=False,
        )
        if result.returncode or result.stdout == path.read_bytes():
            continue
        try:
            metadata, previous_body = parse(result.stdout)
        except ValueError:
            continue
        return metadata, previous_body
    return None


def _finding_text(findings: list[ReviewFinding]) -> dict[str, str]:
    return {
        finding.id: finding.heading
        + "\n"
        + re.sub(r"^\*\*Status:\*\*.*$", "", finding.text, flags=re.MULTILINE).strip()
        for finding in findings
    }


def _has_fix_commit(
    mapping: dict[str, object],
    review: Path,
    finding_id: str,
    repo: Path | str | None,
) -> bool:
    base, head = mapping.get("base"), mapping.get("head")
    if not isinstance(base, str) or not isinstance(head, str):
        return False
    repository = _repository_for_range(review, base, head, repo)
    if repository is None:
        logger.warning(
            "cannot check fixed high finding %s: base/head commits are unavailable",
            finding_id,
        )
        return True
    result = subprocess.run(
        ["git", "-C", str(repository), "log", "--format=%s", f"{base}..{head}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and any(
        line.startswith(f"fix({finding_id}):") for line in result.stdout.splitlines()
    )


def _repository_for_range(
    review: Path, base: str, head: str, repo: Path | str | None
) -> Path | None:
    candidates = [Path(repo)] if repo is not None else []
    candidates.extend((review.parent, Path.cwd()))
    seen: set[Path] = set()
    for candidate in candidates:
        result = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode or not result.stdout.strip():
            continue
        root = Path(result.stdout.strip()).resolve()
        if root in seen:
            continue
        seen.add(root)
        commits = [
            subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--verify", f"{ref}^{{commit}}"],
                capture_output=True,
                check=False,
            )
            for ref in (base, head)
        ]
        if all(item.returncode == 0 for item in commits):
            return root
    return None
