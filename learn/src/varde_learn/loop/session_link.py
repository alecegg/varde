"""Provider-independent linking of worker sessions to tool-call evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SessionSource(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class ParentSession:
    session_id: str
    tool_call_results: tuple[str, ...]


@dataclass(frozen=True)
class CandidateSession:
    session_id: str


@dataclass(frozen=True)
class WorkerLink:
    parent_id: str
    evidence: str


def link_workers(
    parents: list[ParentSession] | tuple[ParentSession, ...],
    candidates: list[CandidateSession] | tuple[CandidateSession, ...],
) -> list[WorkerLink | None | tuple[str, ...]]:
    """Link a candidate only when exactly one parent mentions its ID.

    Ambiguous entries are a sorted tuple of parent IDs; unmatched entries are
    ``None``. Repeated mentions by one parent use its first evidence string.
    """
    links: list[WorkerLink | None | tuple[str, ...]] = []
    for candidate in candidates:
        matches = [
            (parent.session_id, evidence)
            for parent in parents
            if (
                evidence := next(
                    (
                        line
                        for line in parent.tool_call_results
                        if candidate.session_id in line
                    ),
                    None,
                )
            )
            is not None
        ]
        if not matches:
            links.append(None)
        elif len(matches) == 1:
            parent_id, evidence = matches[0]
            links.append(WorkerLink(parent_id, evidence))
        else:
            links.append(tuple(sorted({parent_id for parent_id, _ in matches})))
    return links
