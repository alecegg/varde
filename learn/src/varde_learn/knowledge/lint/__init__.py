"""Report-only structural checks for a markdown knowledge bundle."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from varde_learn.knowledge.bundle import is_artifact_dir, is_reserved
from varde_learn.knowledge.concept import Concept
from varde_learn.knowledge.frontmatter import FrontmatterError
from varde_learn.knowledge.lint.links import extract_links


class Severity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class CheckKind(str, Enum):
    ORPHANED_CONCEPT = "orphaned_concept"
    BROKEN_LINK = "broken_link"
    MISSING_INDEX = "missing_index"
    MALFORMED_CONCEPT = "malformed_concept"
    UNREADABLE_ENTRY = "unreadable_entry"


@dataclass(frozen=True)
class LintIssue:
    severity: Severity
    check_kind: CheckKind
    path: Path
    message: str


@dataclass
class LintReport:
    issues: list[LintIssue]


class LintError(OSError):
    """A bundle root could not be read."""

    def __init__(self, path: Path, source: OSError) -> None:
        self.path = path
        self.source = source
        super().__init__(f"failed to read bundle directory `{path}`: {source}")


@dataclass(frozen=True)
class LintOptions:
    require_index: bool = False


def lint(bundle: str | Path) -> LintReport:
    """Lint a bundle without enabling the optional missing-index check."""
    return lint_with_options(bundle, LintOptions())


def lint_with_options(bundle: str | Path, options: LintOptions) -> LintReport:
    root = Path(bundle)
    issues: list[LintIssue] = []
    concepts: list[tuple[Path, Concept]] = []
    index_links: list[tuple[Path, str]] = []
    _walk(root, issues, concepts, index_links, options, root=True)
    _check_broken_links(concepts, root, issues)
    _check_orphans(concepts, index_links, root, issues)
    issues.sort(
        key=lambda issue: (
            0 if issue.severity is Severity.ERROR else 1,
            str(issue.path),
            issue.check_kind.value,
        )
    )
    return LintReport(issues)


def _walk(
    directory: Path,
    issues: list[LintIssue],
    concepts: list[tuple[Path, Concept]],
    index_links: list[tuple[Path, str]],
    options: LintOptions,
    *,
    root: bool = False,
) -> None:
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        if root:
            raise LintError(directory, exc) from exc
        issues.append(
            LintIssue(
                Severity.ERROR,
                CheckKind.UNREADABLE_ENTRY,
                directory,
                (
                    f"failed to read directory `{directory}`: failed to read bundle "
                    f"directory `{directory}`: {exc}"
                ),
            )
        )
        return
    has_concept = False
    has_index = False
    for path in entries:
        found_concept, found_index = _walk_entry(
            path, issues, concepts, index_links, options
        )
        has_concept |= found_concept
        has_index |= found_index
    if options.require_index and has_concept and not has_index:
        issues.append(
            LintIssue(
                Severity.WARNING,
                CheckKind.MISSING_INDEX,
                directory,
                f"directory `{directory}` contains Concept files but no `index.md`",
            )
        )


def _walk_entry(
    path: Path,
    issues: list[LintIssue],
    concepts: list[tuple[Path, Concept]],
    index_links: list[tuple[Path, str]],
    options: LintOptions,
) -> tuple[bool, bool]:
    name = path.name
    if name.startswith(".") or is_artifact_dir(name) or path.is_symlink():
        return False, False
    try:
        is_directory = path.is_dir()
        is_file = path.is_file()
    except OSError:
        return False, False
    if is_directory:
        _walk(path, issues, concepts, index_links, options)
        return False, False
    if not is_file:
        return False, False
    if name == "index.md":
        try:
            body = path.read_text(encoding="utf-8")
        except OSError, UnicodeError:
            pass
        else:
            index_links.append((_normalize_path(path), body))
        return False, True
    if is_reserved(name) or not name.endswith(".md"):
        return False, False
    _scan_concept_file(path, issues, concepts)
    return True, False


def _scan_concept_file(
    path: Path, issues: list[LintIssue], concepts: list[tuple[Path, Concept]]
) -> None:
    try:
        data = path.read_bytes()
    except OSError as exc:
        issues.append(
            LintIssue(
                Severity.ERROR,
                CheckKind.UNREADABLE_ENTRY,
                path,
                f"failed to read `{path}`: {exc}",
            )
        )
        return
    try:
        concept = Concept.from_bytes(data, path.name[:-3])
    except FrontmatterError as exc:
        if "delimited by `---` frontmatter markers" in str(exc):
            return
        issues.append(
            LintIssue(
                Severity.ERROR,
                CheckKind.MALFORMED_CONCEPT,
                path,
                f"`{path}` is not a valid concept: {exc}",
            )
        )
        return
    concepts.append((_normalize_path(path), concept))


def _check_broken_links(
    concepts: list[tuple[Path, Concept]], bundle: Path, issues: list[LintIssue]
) -> None:
    for path, concept in concepts:
        for target in extract_links(concept.body):
            resolved = _resolve_link(target, bundle, path)
            if not resolved.is_file():
                issues.append(
                    LintIssue(
                        Severity.ERROR,
                        CheckKind.BROKEN_LINK,
                        resolved,
                        (
                            f"broken bundle-internal link `{target}` referenced from "
                            f"`{path}`"
                        ),
                    )
                )


def _check_orphans(
    concepts: list[tuple[Path, Concept]],
    index_links: list[tuple[Path, str]],
    bundle: Path,
    issues: list[LintIssue],
) -> None:
    incoming: set[Path] = set()
    for path, concept in concepts:
        incoming.update(
            _resolve_link(target, bundle, path)
            for target in extract_links(concept.body)
            if _resolve_link(target, bundle, path) != path
        )
    for path, body in index_links:
        incoming.update(
            _resolve_link(target, bundle, path) for target in extract_links(body)
        )
    normalized_bundle = _normalize_path(bundle)
    for path, _ in concepts:
        try:
            first = path.relative_to(normalized_bundle).parts[0]
        except ValueError, IndexError:
            first = ""
        if first in {"conclusions", "promotions"}:
            continue
        if path not in incoming:
            issues.append(
                LintIssue(
                    Severity.WARNING,
                    CheckKind.ORPHANED_CONCEPT,
                    path,
                    f"no other Concept in the bundle links to `{path}`",
                )
            )


def _normalize_path(path: Path) -> Path:
    parts: list[str] = []
    for part in path.parts:
        if part == ".":
            continue
        if part == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            else:
                parts.append(part)
        else:
            parts.append(part)
    return Path(*parts)


def _resolve_link(target: str, bundle: Path, source: Path) -> Path:
    if target.startswith("/"):
        return _normalize_path(bundle / target[1:])
    return _normalize_path(source.parent / target)


__all__ = [
    "CheckKind",
    "LintError",
    "LintIssue",
    "LintOptions",
    "LintReport",
    "Severity",
    "lint",
    "lint_with_options",
]
