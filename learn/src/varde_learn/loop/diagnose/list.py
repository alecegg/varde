"""Repository-scoped session listing shared by diagnose harness adapters."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..errors import Diagnose
from ..session_link import CandidateSession, ParentSession, WorkerLink, link_workers
from .model import HARNESS_ADAPTERS, MAX_DISCOVERY_FILES, DiagnosticHarness

MAX_PASEO_RECORD_BYTES = 64 * 1024


class ListHarness(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    OPENCODE = "opencode"
    ALL = "all"


@dataclass
class ListRequest:
    harness: ListHarness | str
    repo: Path
    codex_home: Path
    claude_projects_root: Path
    opencode_data_root: Path
    paseo_home: Path | None = None
    limit: int = 10
    offset: int = 0
    include_paseo_worktrees: bool = False
    run: str | None = None


@dataclass
class ListedWorker:
    harness: str
    session_id: str
    source: str
    link: Any
    path: str | None = None


@dataclass
class ListedSession:
    harness: str
    session_id: str
    source: str
    link: Any
    started_at: str | None
    cwd: str | None
    root: bool | str
    workers: list[ListedWorker] = field(default_factory=list)
    path: str | None = None


@dataclass
class SessionList:
    sessions: list[ListedSession]
    warnings: list[str] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"sessions": [asdict(item) for item in self.sessions]}


@dataclass
class RootDiscoveryRow:
    harness: str
    root: str
    path: str
    kind: str
    parent_id: str | None
    session_id: str
    identity: str
    parent_identity: str | None
    parent_known: bool
    started_at: str | None
    cwd: str | None
    retro_analyst: bool
    status: str = "ok"
    reason: str | None = None


@dataclass
class RootDiscovery:
    sessions: list[RootDiscoveryRow]
    warnings: list[str] = field(default_factory=list)


def discover_root(
    harness: ListHarness | str,
    root: Path,
    limit: int = MAX_DISCOVERY_FILES,
    window_start: datetime | None = None,
    pending_paths: set[str] | None = None,
    include_skipped: bool = False,
) -> RootDiscovery:
    """Run provider discovery against one data root, without repository filtering."""
    selected = ListHarness(harness)
    adapter = HARNESS_ADAPTERS.get(DiagnosticHarness(selected.value))
    if adapter is None:
        from .model import harness_adapter

        adapter = harness_adapter(DiagnosticHarness(selected.value))
    method = getattr(adapter, "discover_root", None)
    if method is None:
        raise ValueError(f"{selected.value} does not support root discovery")
    sessions, warnings = method(
        root, limit, window_start, pending_paths, include_skipped
    )
    rows = []
    for session in sessions:
        path = str(_get(session, "path", _get(session, "source", "")))
        parent_identity = _get(session, "parent_identity")
        parent_id = _get(session, "parent_id")
        if parent_id is None and parent_identity:
            parent_id = str(parent_identity).rsplit(":", 1)[-1]
        rows.append(
            RootDiscoveryRow(
                str(_get(session, "harness", selected.value)),
                str(root),
                path,
                str(_get(session, "kind", "session")),
                parent_id,
                str(_get(session, "session_id", "")),
                str(_get(session, "identity", "")),
                parent_identity,
                bool(_get(session, "parent_known", False)),
                _get(session, "started_at"),
                _get(session, "cwd"),
                bool(_get(session, "retro_analyst", False)),
                str(_get(session, "status", "ok")),
                _get(session, "reason"),
            )
        )
    return RootDiscovery(rows, warnings)


@dataclass
class _PaseoAgent:
    id: str
    provider: str
    session_id: str
    parent_agent_id: str | None


def list_sessions(request: ListRequest) -> SessionList:
    """Discover sessions, resolve roots, and attach verified workers."""
    try:
        harness = ListHarness(request.harness)
    except ValueError as exc:
        raise ValueError("--harness must be codex, claude, opencode, or all") from exc
    if not 1 <= request.limit <= 10:
        raise ValueError("--limit must be between 1 and 10")
    if request.offset < 0:
        raise ValueError("--offset must be non-negative")
    if request.run is not None and not request.run.strip():
        raise ValueError("--run requires a session ID")
    repo = request.repo.resolve(strict=True)
    roots = {
        "codex": request.codex_home,
        "claude": request.claude_projects_root,
        "opencode": request.opencode_data_root,
        "paseo": request.paseo_home,
    }
    selected = (
        [item for item in DiagnosticHarness if item is not DiagnosticHarness.PI]
        if harness is ListHarness.ALL
        else [DiagnosticHarness(harness.value)]
    )
    candidates, warnings = _discover(selected, harness, repo, roots)
    candidates = [
        item
        for item in candidates
        if not _is_retro(item)
        and _in_repo(
            _get(item, "cwd"),
            repo,
            request.paseo_home if request.include_paseo_worktrees else None,
        )
    ]

    paseo_agents: list[_PaseoAgent] = []
    if request.paseo_home is not None:
        try:
            paseo_agents = _read_paseo_agents(request.paseo_home)
        except OSError, ValueError, json.JSONDecodeError:
            warning = (
                "Paseo agent records could not be read; Paseo linkage was "
                "skipped and native parent links were used where available"
            )
            warnings.append(warning)
    parents, roots_known, tool_links = _resolve_links(candidates, paseo_agents)
    root_for = [
        _resolve_root(index, parents, roots_known) for index in range(len(candidates))
    ]
    root_indices = [index for index, root in enumerate(root_for) if root[0] == index]
    root_indices.sort(key=lambda index: _recency_key(candidates[index]))

    if request.run is not None:
        matches = [
            index
            for index, item in enumerate(candidates)
            if _get(item, "session_id") == request.run
        ]
        if not matches:
            matches = [
                index
                for index, item in enumerate(candidates)
                if request.run in (_get(item, "aliases", []) or [])
            ]
        if len(matches) == 0:
            raise ValueError(f"session `{request.run}` was not found in --repository")
        if len(matches) > 1:
            raise ValueError(
                f"session `{request.run}` matches multiple harness sessions"
            )
        selected_roots = [root_for[matches[0]][0]]
    else:
        selected_roots = _select_roots(
            root_indices, candidates, harness, request.limit, request.offset
        )

    sessions = []
    for root_index in selected_roots:
        item = candidates[root_index]
        worker_indices = [
            index
            for index, (root, _) in enumerate(root_for)
            if index != root_index and root == root_index
        ]
        worker_indices.sort(
            key=lambda index: (
                _recency_key(candidates[index]),
                str(_get(candidates[index], "harness")),
            )
        )
        workers = [
            _listed_worker(
                candidates[index], _worker_link(candidates[index], tool_links)
            )
            for index in worker_indices
        ]
        sessions.append(
            ListedSession(
                harness=str(_get(item, "harness")),
                session_id=str(_get(item, "session_id")),
                source=str(_get(item, "listing_source", "active")),
                link=_root_link(item),
                started_at=_get(item, "started_at"),
                cwd=_get(item, "cwd"),
                root=True if root_for[root_index][1] else "unknown",
                workers=workers,
                path=_get(item, "source"),
            )
        )
    return SessionList(sessions, warnings)


def _discover(selected, harness: ListHarness, repo: Path, roots: dict[str, Any]):
    candidates: list[Any] = []
    warnings: list[str] = []
    for provider in selected:
        adapter = HARNESS_ADAPTERS.get(provider)
        if adapter is None:
            if harness is ListHarness.ALL:
                warning = (
                    f"{provider.value} discovery adapter is not registered; "
                    "sessions were skipped"
                )
                warnings.append(warning)
                continue
            raise ValueError(f"{provider.value} discovery adapter is not registered")
        try:
            found = adapter.discover(repo=repo, roots=roots, limit=MAX_DISCOVERY_FILES)
        except Diagnose as error:
            if harness is not ListHarness.ALL:
                raise
            warnings.append(f"{provider.value} discovery failed: {error}")
            continue
        candidates.extend(found)
    return candidates, warnings


def _resolve_links(candidates: list[Any], agents: list[_PaseoAgent]):
    paseo_by_id = {}
    duplicate_ids = set()
    for agent in agents:
        if agent.id in paseo_by_id:
            duplicate_ids.add(agent.id)
        paseo_by_id[agent.id] = agent
    for duplicate in duplicate_ids:
        paseo_by_id.pop(duplicate, None)
    paseo_candidate = {}
    for agent in agents:
        if agent.id in duplicate_ids:
            continue
        candidate = _find_paseo_candidate(agent, candidates)
        if candidate is not None:
            paseo_candidate[agent.id] = candidate

    parents: list[int | None] = [None] * len(candidates)
    roots_known = [False] * len(candidates)
    links: list[WorkerLink | None | tuple[str, ...]] = [None] * len(candidates)
    by_identity: dict[str, list[int]] = {}
    for index, item in enumerate(candidates):
        by_identity.setdefault(str(_get(item, "identity")), []).append(index)

    codex_indices = [
        index
        for index, item in enumerate(candidates)
        if _get(item, "harness") == "codex"
    ]
    parent_sessions = [
        ParentSession(
            str(_get(candidates[index], "session_id")),
            tuple(_get(candidates[index], "tool_call_results", ())),
        )
        for index in codex_indices
    ]
    tool_candidates = [
        CandidateSession(str(_get(candidates[index], "session_id")))
        for index in codex_indices
    ]
    for index, link in zip(
        codex_indices, link_workers(parent_sessions, tool_candidates), strict=True
    ):
        links[index] = link
    for child, item in enumerate(candidates):
        agent = next(
            (agent for agent in agents if paseo_candidate.get(agent.id) == child), None
        )
        if agent is not None and agent.parent_agent_id:
            parents[child] = paseo_candidate.get(agent.parent_agent_id)
            roots_known[child] = parents[child] is not None
            continue
        identity = _get(item, "parent_identity")
        if identity:
            matches = by_identity.get(identity, [])
            if len(matches) == 1 and matches[0] != child:
                parents[child] = matches[0]
            roots_known[child] = False
            continue
        link = links[child]
        if isinstance(link, WorkerLink):
            matches = [
                index
                for index, parent in enumerate(candidates)
                if _get(parent, "session_id") == link.parent_id
                and _get(parent, "harness") == "codex"
            ]
            if len(matches) == 1:
                parents[child] = matches[0]
                roots_known[child] = True
        else:
            roots_known[child] = bool(_get(item, "parent_known", False))
    return parents, roots_known, links


def _read_paseo_agents(home: Path) -> list[_PaseoAgent]:
    root = home / "agents"
    if not root.exists():
        return []
    agents = []
    scanned = 0
    for provider_dir in root.iterdir():
        scanned += 1
        if scanned > MAX_DISCOVERY_FILES:
            raise ValueError("Paseo agent discovery exceeded its entry bound")
        if provider_dir.is_symlink() or not provider_dir.is_dir():
            continue
        for path in provider_dir.iterdir():
            scanned += 1
            if scanned > MAX_DISCOVERY_FILES:
                raise ValueError("Paseo agent discovery exceeded its entry bound")
            if path.suffix != ".json" or path.is_symlink() or not path.is_file():
                continue
            if path.stat().st_size > MAX_PASEO_RECORD_BYTES:
                raise ValueError("Paseo agent record exceeded its byte bound")
            value = json.loads(path.read_bytes())
            if not isinstance(value, dict):
                raise ValueError("invalid Paseo agent record")
            provider = value.get("provider")
            persistence = value.get("persistence")
            session_id = (
                persistence.get("sessionId") if isinstance(persistence, dict) else None
            )
            agent_id = path.stem
            if (
                not isinstance(provider, str)
                or not isinstance(session_id, str)
                or not agent_id
                or not session_id
            ):
                continue
            labels = value.get("labels")
            parent = (
                labels.get("paseo.parent-agent-id")
                if isinstance(labels, dict)
                else None
            )
            agents.append(
                _PaseoAgent(
                    agent_id,
                    provider,
                    session_id,
                    parent if isinstance(parent, str) and parent else None,
                )
            )
    return agents


def _find_paseo_candidate(agent: _PaseoAgent, candidates: list[Any]) -> int | None:
    provider = agent.provider.lower()
    if provider not in {"codex", "claude", "opencode"}:
        return None
    matches = [
        (index, item)
        for index, item in enumerate(candidates)
        if _get(item, "harness") == provider
        and agent.session_id in (_get(item, "aliases", []) or [])
    ]
    by_agent = [
        index
        for index, item in matches
        if agent.id in (_get(item, "aliases", []) or [])
    ]
    if len(by_agent) == 1:
        return by_agent[0]
    if len(by_agent) > 1:
        return None
    by_public_id = [
        index for index, item in matches if _get(item, "session_id") == agent.session_id
    ]
    if len(by_public_id) == 1:
        return by_public_id[0]
    return matches[0][0] if len(matches) == 1 else None


def _resolve_root(
    start: int, parents: list[int | None], roots_known: list[bool]
) -> tuple[int, bool]:
    current = start
    seen = set()
    while True:
        if current in seen:
            return start, False
        seen.add(current)
        parent = parents[current]
        if parent is None:
            return current, roots_known[current]
        current = parent


def _select_roots(
    root_indices: list[int],
    candidates: list[Any],
    harness: ListHarness,
    limit: int,
    offset: int = 0,
) -> list[int]:
    selected = []
    target = limit + offset
    if harness is ListHarness.ALL:
        representatives = [
            next(
                (
                    index
                    for index in root_indices
                    if _get(candidates[index], "harness") == provider
                ),
                None,
            )
            for provider in ("codex", "claude", "opencode")
        ]
        representatives = [index for index in representatives if index is not None]
        if len(representatives) <= target:
            selected = representatives
    for index in root_indices:
        if len(selected) == target:
            break
        if index not in selected:
            selected.append(index)
    ordered = sorted(selected, key=lambda index: _recency_key(candidates[index]))
    return ordered[offset : offset + limit]


def _listed_worker(item: Any, link: Any) -> ListedWorker:
    return ListedWorker(
        str(_get(item, "harness")),
        str(_get(item, "session_id")),
        str(_get(item, "listing_source", "active")),
        link,
        _get(item, "source"),
    )


def _root_link(item: Any) -> Any:
    parent = _get(item, "parent_identity")
    return {"parent_id": parent, "evidence": parent} if parent else "unlinked"


def _worker_link(item: Any, tool_link: Any) -> Any:
    parent = _get(item, "parent_identity")
    if parent:
        return {"parent_id": parent, "evidence": parent}
    if isinstance(tool_link, WorkerLink):
        return {
            "parent_id": f"codex:{tool_link.parent_id}",
            "evidence": tool_link.evidence,
        }
    return "unlinked"


def _get(item: Any, name: str, default: Any = None) -> Any:
    return (
        item.get(name, default)
        if isinstance(item, dict)
        else getattr(item, name, default)
    )


def _is_retro(item: Any) -> bool:
    return bool(_get(item, "retro_analyst", False)) or str(
        _get(item, "session_id", "")
    ).startswith("varde-retro-analyst")


def _in_repo(cwd: str | None, repo: Path, paseo_home: Path | None = None) -> bool:
    if not cwd:
        return False
    try:
        resolved_cwd = Path(cwd).resolve()
        if os.path.commonpath((str(resolved_cwd), str(repo))) == str(repo):
            return True
        if paseo_home is None:
            return False
        worktrees = (paseo_home / "worktrees").resolve()
        if os.path.commonpath((str(resolved_cwd), str(worktrees))) != str(worktrees):
            return False
        worktree_common = _git_common_dir(resolved_cwd)
        return worktree_common is not None and worktree_common == _git_common_dir(repo)
    except OSError, ValueError:
        return False


def _git_common_dir(path: Path) -> Path | None:
    try:
        result = subprocess.run(  # noqa: S603 - fixed Git query for the selected repository.
            [  # noqa: S607 - resolve the installed Git CLI for this query.
                "git",
                "-C",
                str(path),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except OSError, subprocess.SubprocessError:
        return None
    if result.returncode:
        return None
    return Path(result.stdout.strip()).resolve()


def _recency_key(item: Any) -> tuple[int, str]:
    timestamp = _get(item, "started_at")
    try:
        recency = (
            int(datetime.fromisoformat(timestamp).timestamp() * 1_000_000_000)
            if timestamp
            else -1
        )
    except AttributeError, TypeError, ValueError, OverflowError:
        recency = -1
    return -recency, str(_get(item, "session_id", ""))
