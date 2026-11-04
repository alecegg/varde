"""Documents under the working dir: safe paths, listing, reading, search."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from varde_learn.docs.pages.assemble import read_markdown
from varde_learn.docs.pages.comments import (
    ANSWER_KINDS,
    fold,
    fold_with_sources,
    mark_latest_decisions,
    read_rows,
)
from varde_learn.docs.pages.include import IncludeError, include_sources

from varde_serve.api.errors import ApiError
from varde_serve.files import SKIP_DIRS, files_with_suffix
from varde_serve.project import Project


def doc_files(working: Path) -> list[Path]:
    return files_with_suffix(working, ".md")


def listed_markdown(candidate: Path, root: Path) -> bool:
    """A markdown file under `root` outside the directories listings hide."""
    if not candidate.is_relative_to(root):
        return False
    hidden = SKIP_DIRS.intersection(candidate.relative_to(root).parts)
    return not hidden and candidate.suffix == ".md" and candidate.is_file()


def resolve_doc(project: Project, relative: str) -> Path:
    """The markdown file `relative` inside the working dir; ApiError otherwise."""
    root = project.working.resolve()
    try:
        candidate = (root / relative).resolve()
    except ValueError, OSError:  # NUL byte or an unreadable path component
        raise ApiError(404, "not_found", "no such document") from None
    if not listed_markdown(candidate, root):
        raise ApiError(404, "not_found", "no such document")
    return candidate


def list_docs(project: Project) -> list[dict[str, str]]:
    return [
        {"path": path.relative_to(project.working).as_posix()}
        for path in doc_files(project.working)
    ]


def plan_store(project: Project) -> Path:
    return project.working / "plans"


def doc_comments(
    project: Project, doc: Path
) -> tuple[list[dict[str, Any]], str | None]:
    """Page comments plus those of included parts, and the include error if any."""
    try:
        sources = include_sources(read_markdown(doc), doc.parent, plan_store(project))
    except (IncludeError, OSError) as error:
        return fold(read_rows(doc)), str(error)
    return fold_with_sources(doc, sources), None


def read_doc(project: Project, relative: str) -> dict[str, Any]:
    doc = resolve_doc(project, relative)
    found, include_error = doc_comments(project, doc)
    comments = mark_latest_decisions(found)
    return {
        "include_error": include_error,
        "path": relative,
        "text": read_markdown(doc),
        "comments": [c for c in comments if c.get("kind") not in ANSWER_KINDS],
        "decisions": [c for c in comments if c.get("kind") in ANSWER_KINDS],
    }


def search_docs(project: Project, needle: str, limit: int) -> list[dict[str, Any]]:
    hits = []
    for path in doc_files(project.working):
        for number, line in enumerate(read_markdown(path).splitlines(), start=1):
            if needle in line.lower():
                relative = path.relative_to(project.working).as_posix()
                hits.append({"path": relative, "line": number, "text": line[:200]})
                break
        if len(hits) >= limit:
            break
    return hits
