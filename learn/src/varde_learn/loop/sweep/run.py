"""I/O orchestration for a deterministic local session sweep."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from varde_data.learn_store_mode import backend_for

from .. import analyzed
from ..calls_retention import prune_calls, retention_days
from ..cli_friction_write import _with_write_store
from ..diagnose import claude as _claude  # noqa: F401
from ..diagnose import codex as _codex  # noqa: F401
from ..diagnose import opencode as _opencode  # noqa: F401
from ..diagnose.list import ListedSession, ListRequest, list_sessions
from ..diagnose.metrics import session_metrics, waste_signals
from ..diagnose.model import harness_adapter
from ..friction_repository import open_repository
from ..improve.tool_bypass import bypass_metric, load_rows
from ..skill_runs import skill_runs
from ..store import write as store_write
from ..store.paths import resolve_store_dir
from ..store.types import FrictionAddMode, FrictionAddRequest
from ..sweep_digest import (
    rank_candidates,
    read_digest,
    render_digest,
    summarize_with_claude,
    summary_config,
    write_digest,
)
from .core import dedupe_against_open, findings_from_metrics, select_unanalyzed


def configured_repos() -> list[Path]:
    config = Path.home() / ".config/varde/learn/sweep.toml"
    if config.exists():
        value = tomllib.loads(config.read_text(encoding="utf-8"))
        repos = value.get("repos", [])
        if not isinstance(repos, list) or any(
            not isinstance(item, str) for item in repos
        ):
            raise ValueError("sweep config repos must be a list of paths")
        return [Path(item).expanduser().resolve() for item in repos]
    source = Path.home() / "source"
    return (
        sorted(
            path
            for path in source.iterdir()
            if path.is_dir() and (path / ".git").exists()
        )
        if source.is_dir()
        else []
    )


def _roots() -> dict[str, Path]:
    from ..diagnose.summary import _roots as roots

    return roots()


def _sessions(repo: Path, roots: dict[str, Path]):
    sessions = []
    warnings = []
    offset = 0
    while True:
        listing = list_sessions(
            ListRequest(
                "all",
                repo,
                roots["codex"],
                roots["claude"],
                roots["opencode"],
                paseo_home=Path(os.environ["PASEO_HOME"])
                if os.environ.get("PASEO_HOME")
                else None,
                limit=10,
                offset=offset,
                include_paseo_worktrees=True,
            )
        )
        sessions.extend(listing.sessions)
        warnings.extend(listing.warnings)
        if len(listing.sessions) < 10:
            return sessions, warnings
        offset += len(listing.sessions)


def _inspect(
    session: dict[str, Any], roots: dict[str, Path]
) -> tuple[dict[str, Any], list[Any]]:
    adapter = harness_adapter(session["harness"])
    request = SimpleNamespace(
        root=roots[session["harness"]],
        source_root=roots[session["harness"]],
        projects_root=roots[session["harness"]],
        session_id=session["session_id"],
        path=Path(session["path"]) if session.get("path") else None,
    )
    records = adapter.inspect(request).records
    metrics: dict[str, Any] = session_metrics(records)
    signals = waste_signals(records)
    metrics["signals"] = [
        {"kind": signal.kind, "count": signal.count, "anchors": signal.anchors}
        for signal in signals
    ]
    anchors = [anchor["index"] for signal in signals for anchor in signal.anchors]
    skills = skill_runs(records, anchors)
    if skills:
        metrics["skills"] = skills
    commands: dict[str, dict[str, int]] = {}
    for record in records:
        tool = getattr(record, "tool_name", None) or (
            record.get("tool_name") if isinstance(record, dict) else None
        )
        if not tool:
            continue
        row = commands.setdefault(
            str(tool),
            {
                "calls": 0,
                "failures": 0,
                "retries": 0,
                "timeouts": 0,
                "permission_denials": 0,
            },
        )
        row["calls"] += 1
        error = getattr(record, "tool_error", None) or (
            record.get("tool_error") if isinstance(record, dict) else None
        )
        status = getattr(record, "tool_status", None) or (
            record.get("tool_status") if isinstance(record, dict) else None
        )
        message = f"{error or ''} {status or ''}".lower()
        if error or str(status).lower() in {"error", "failed", "failure"}:
            row["failures"] += 1
        if "timeout" in message or "timed out" in message:
            row["timeouts"] += 1
        if "permission" in message or "denied" in message:
            row["permission_denials"] += 1
    metrics["command_failures"] = commands
    return metrics, records


def _open_items(store: Path) -> list[dict[str, Any]]:
    log = open_repository(store).event_log()
    state, grouped = log.state, log.grouped_occurrences
    return [
        {
            "status": item.status,
            "dedupe_key": None,
            "occurrences": [
                {"evidence": occurrence.evidence}
                for occurrence in grouped.get(item.event_id, ())
            ],
        }
        for item in state.items
    ]


def _list_sessions(repos: list[Path], roots: dict[str, Path]):
    listed = {}
    failures = []
    all_warnings = []
    seen_warnings = set()
    for repo in repos:
        try:
            sessions, warnings = _sessions(repo, roots)
            for warning in warnings:
                if warning not in seen_warnings:
                    seen_warnings.add(warning)
                    all_warnings.append(warning)
            for session in sessions:
                session_row = (
                    asdict(session) if isinstance(session, ListedSession) else session
                )
                listed.setdefault(
                    (session_row["harness"], session_row["session_id"]),
                    (repo, session_row),
                )
        except Exception as error:  # noqa: BLE001 - isolate repository failures
            failures.append({"repo": str(repo), "error": str(error)[:200]})
    return list(listed.values()), failures, all_warnings


def _select_candidates(listed, ledger, limit):
    candidates = []
    repo_for = {}
    for repo, session in listed:
        for row in select_unanalyzed([session], ledger):
            key = (row["harness"], row["session_id"])
            if key in repo_for:
                continue
            candidates.append(row)
            repo_for[key] = str(repo)
    return (candidates[:limit] if limit is not None else candidates), repo_for


def _record_candidate(  # noqa: PLR0913, PLR0917 - one call site; rows load once per sweep
    session, repo, roots, store, open_items, run_at, bypass_rows=()
):
    harness, session_id = session["harness"], session["session_id"]
    metrics, records = _inspect(session, roots)
    bypass = bypass_metric(records, session_id, bypass_rows)
    if bypass:
        metrics["tool_bypass"] = bypass
    findings = dedupe_against_open(
        findings_from_metrics(metrics, session_id), open_items
    )
    for finding in findings:
        key = finding["dedupe_key"]
        title = finding["title"]
        evidence = (
            f"sweep-key:{key} session:{harness}/{session_id} "
            f"{json.dumps(finding['evidence'], sort_keys=True)}"
        )

        def write_finding(repository, title=title, evidence=evidence, repo=repo):
            return store_write.add_friction(
                repository,
                FrictionAddRequest(
                    FrictionAddMode.create("varde learn sweep", title, None, False),
                    evidence,
                    Path(repo),
                ),
            )

        _with_write_store(write_finding)
        open_items.append(
            {
                "status": "open",
                "dedupe_key": key,
                "occurrences": [{"evidence": evidence}],
            }
        )
    analyzed.mark(
        store,
        harness,
        session_id,
        run_at,
        "learn sweep",
        metrics,
        friction_added=[finding["dedupe_key"] for finding in findings],
    )
    return findings, len(findings)


def _summary_settings():
    try:
        return (*summary_config(), None)
    except (OSError, TypeError, ValueError) as error:
        return False, 2000, f"invalid summary config: {error}"[:200]


def _make_digest(store, run_at, analyzed_count, findings, model_enabled, token_cap):
    run_date = datetime.fromisoformat(run_at).date()
    if not analyzed_count:
        return read_digest(store, run_date), None, None
    ranked = rank_candidates(findings)
    digest = render_digest(ranked)
    summary_error = None
    model_tokens = None
    if model_enabled:
        try:
            summary, model_tokens = summarize_with_claude(digest, token_cap=token_cap)
            if summary:
                digest = summary
        except Exception as error:  # noqa: BLE001 - model summary is optional
            summary_error = f"summary model failed: {error}"[:200]
    write_digest(store, run_date, digest, ranked)
    return (
        {
            "date": run_date.isoformat(),
            "text": digest,
            "candidates": ranked,
        },
        model_tokens,
        summary_error,
    )


def _prune_calls(store: Path, result: dict[str, Any]) -> None:
    """Prune used call rows after analysis; a failure is a warning."""
    try:
        if backend_for(store, "calls") != "sqlite":
            return
        pruned = prune_calls(store, retention_days())
        result["calls_pruned"] = pruned["deleted"]
    except Exception as error:  # noqa: BLE001 - pruning must not fail the sweep
        result["warnings"].append(f"calls prune failed: {error}"[:200])


def run_sweep(*, dry_run: bool = False, limit: int | None = None) -> dict[str, Any]:
    repos = configured_repos()
    roots = _roots()
    store = resolve_store_dir()
    ledger = analyzed.read_all(store)
    listed, failures, warnings = _list_sessions(repos, roots)
    candidates, repo_for = _select_candidates(listed, ledger, limit)
    result = {
        "run_at": datetime.now(UTC).isoformat(),
        "repos": [str(repo) for repo in repos],
        "sessions_seen": len(
            {
                (session["harness"], session["session_id"])
                for _, root in listed
                for session in (root, *root.get("workers", []))
            }
        ),
        "analyzed": 0,
        "skipped": 0,
        "friction_added": 0,
        "calls_pruned": 0,
        "failures": failures,
        "warnings": warnings,
        "digest": None,
        "model_tokens": None,
        "sessions": [],
    }
    if dry_run:
        result["sessions"] = candidates
        result["skipped"] = result["sessions_seen"] - len(candidates)
        return result
    model_enabled, token_cap, summary_error = _summary_settings()
    open_items = _open_items(store)
    bypass_rows, bypass_notice = load_rows()
    if bypass_notice:
        result["warnings"].append(bypass_notice)
    all_findings = []
    for session in candidates:
        harness, session_id = session["harness"], session["session_id"]
        repo = repo_for[(harness, session_id)]
        try:
            findings, friction_added = _record_candidate(
                session,
                repo,
                roots,
                store,
                open_items,
                result["run_at"],
                bypass_rows,
            )
            all_findings.extend(findings)
            result["analyzed"] += 1
            result["friction_added"] += friction_added
        except Exception as error:  # noqa: BLE001 - isolate session failures
            result["failures"].append(
                {
                    "repo": repo,
                    "harness": harness,
                    "session": session_id,
                    "error": str(error)[:200],
                }
            )
        result["sessions"].append({"harness": harness, "session_id": session_id})
    result["skipped"] = result["sessions_seen"] - len(candidates)
    digest, model_tokens, model_error = _make_digest(
        store,
        result["run_at"],
        result["analyzed"],
        all_findings,
        model_enabled,
        token_cap,
    )
    result["digest"] = digest
    result["model_tokens"] = model_tokens
    _prune_calls(store, result)
    result["summary_error"] = model_error or summary_error
    return result
