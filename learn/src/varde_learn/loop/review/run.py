"""Orchestrate one windowed daily learn review."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from varde_data.errors import Locked
from varde_data.locking import file_lock
from varde_data.records.friction import OccurrenceAppended

from .. import analyzed
from ..diagnose.metrics import session_metrics, waste_signals
from ..diagnose.model import harness_adapter
from ..friction_repository import open_repository
from ..sources import load_locations
from ..store.paths import resolve_store_dir
from . import spend
from .digest import build_digest
from .extract import (
    Budget,
    Runner,
    extract_batch,
    mark_review_row,
    review_config,
)
from .inventory import build_inventory
from .ledger import fingerprint, read_index, select_pending, write_imported
from .report import friction_candidates, render_report, write_report
from .spend_compare import compare
from .synthesis import synthesize


def _window(value: str, store: Path, now: datetime) -> tuple[datetime, datetime]:
    today = now.date()
    if value == "yesterday":
        day = today - timedelta(days=1)
        start = datetime.combine(day, time.min, UTC)
        return start, start + timedelta(days=1) - timedelta(microseconds=1)
    if value == "since-last":
        previous = []
        for row in read_index(store).values():
            if row.get("source") != "review" or row.get("status") != "complete":
                continue
            try:
                previous.append(datetime.fromisoformat(str(row["run_at"])))
            except KeyError, ValueError:
                continue
        start = (
            max(previous)
            if previous
            else datetime.combine(today - timedelta(days=1), time.min, UTC)
        )
        start = max(start, now - timedelta(days=7))
        return start.astimezone(UTC), now.astimezone(UTC)
    try:
        day = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            "--window must be yesterday, since-last, or YYYY-MM-DD"
        ) from error
    if day.isoformat() != value:
        raise ValueError("--window date must use YYYY-MM-DD") from None
    start = datetime.combine(day, time.min, UTC)
    return start, start + timedelta(days=1) - timedelta(microseconds=1)


def _inspect(row: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    adapter = harness_adapter(row["harness"])
    root = Path(row["root"])
    request = SimpleNamespace(
        root=root,
        source_root=root,
        projects_root=root,
        session_id=row["session_id"],
        path=Path(row["path"].partition("#")[0]),
    )
    inspection = adapter.inspect(request)
    records = [*inspection.records, *getattr(inspection, "usage_records", [])]
    metrics: dict[str, Any] = session_metrics(records)
    metrics["signals"] = [
        {"kind": item.kind, "count": item.count, "anchors": item.anchors}
        for item in waste_signals(records)
    ]
    return records, metrics


def _inspect_pending(row: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    if row.get("fingerprint_error"):
        raise OSError(str(row["fingerprint_error"]))
    return _inspect(row)


def _inspect_for_spend(
    row: dict[str, Any], window: tuple[datetime, datetime]
) -> tuple[tuple[list[Any], dict[str, Any]], dict[str, Any]]:
    """Inspect once and retain only windowed spend rows and attribution metadata."""
    inspected = _inspect_pending(row)
    records, _metrics = inspected
    first_prompt = next(
        (
            getattr(record, "text_excerpt", "")
            for record in records
            if getattr(record, "role", "") in {"user", "human"}
            and getattr(record, "text_excerpt", None)
        ),
        next(
            (
                getattr(record, "text_excerpt", "")
                for record in records
                if getattr(record, "text_excerpt", None)
            ),
            "",
        ),
    )
    spend_session = spend.prepare_session(
        {
            "harness": row["harness"],
            "session_id": row["session_id"],
            "project": row.get("project"),
            "records": records,
            "first_prompt": first_prompt,
            "is_subagent": row.get("kind") == "subagent",
            "parent_session_id": row.get("parent_id"),
        },
        window[0],
        window[1],
    )
    return inspected, spend_session


def _require_inspected(
    inspected: tuple[list[Any], dict[str, Any]] | None,
    inspection_error: Exception | None,
) -> tuple[list[Any], dict[str, Any]]:
    if inspected is not None:
        return inspected
    if inspection_error is not None:
        raise inspection_error
    raise OSError("session inspection failed")


def _record_failed_spend(
    spend_sessions: list[dict[str, Any]], row: dict[str, Any]
) -> None:
    spend_sessions.append(
        {
            "harness": row["harness"],
            "session_id": row["session_id"],
            "inspection_status": "inspection_failed",
            "usage_rows": [],
            "coverage": {},
        }
    )


def _collect_sessions(
    rows: list[dict[str, Any]],
    pending: list[dict[str, Any]],
    index: dict[tuple[str, str], dict[str, Any]],
    options: dict[str, Any],
) -> tuple[
    list[Mapping[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    list[str],
    list[tuple[dict[str, Any], dict[str, Any]]],
    list[dict[str, Any]],
]:
    observations: list[Mapping[str, Any]] = []
    results: dict[tuple[str, str], dict[str, Any]] = {}
    prompts: list[str] = []
    prompt_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    spend_sessions: list[dict[str, Any]] = []
    pending_by_key = {(row["harness"], row["session_id"]): row for row in pending}
    for row in rows:
        key = (row["harness"], row["session_id"])
        prior = index.get(key, {})
        output = {
            k: row.get(k)
            for k in ("harness", "session_id", "kind", "parent_id", "cwd", "project")
        }
        output.update(
            status="skipped" if row.get("status") != "analyzable" else "analyzed",
            reason=row.get("reason"),
            tokens=0,
        )
        inspected = None
        inspection_error = None
        if row.get("status") == "analyzable" and not options["dry_run"]:
            try:
                inspected, spend_session = _inspect_for_spend(row, options["window"])
                spend_sessions.append(spend_session)
            except Exception as error:  # noqa: BLE001 - output and ledger retain this error
                inspection_error = error
                _record_failed_spend(spend_sessions, row)
        if row.get("status") == "failed":
            output["status"] = "failed"
        elif row.get("status") != "analyzable":
            output["status"] = "skipped"
        elif inspection_error is not None:
            output.update(status="failed", reason=str(inspection_error)[:200])
            if not options["no_model"]:
                mark_review_row(
                    options["store"],
                    {
                        **row,
                        "status": "failed",
                        "reason": str(inspection_error),
                        "run_at": options["run_at"],
                    },
                    latest_by_key=index,
                )
        elif key not in pending_by_key:
            output.update(
                status=prior.get("status", "analyzed"), reason="already reviewed"
            )
        elif options["dry_run"]:
            output.update(status="analyzed", reason="would analyze")
        else:
            try:
                records, metrics = _require_inspected(inspected, inspection_error)
                row["resume_position"] = len(records)
                if options["no_model"]:
                    observations.append(
                        {
                            "harness": row["harness"],
                            "session_id": row["session_id"],
                            "metrics": metrics,
                        }
                    )
                    results[key] = {
                        "row": row,
                        "metrics": metrics,
                        "status": "analyzed",
                    }
                else:
                    selected = pending_by_key[key]
                    resume_position = int(selected.get("resume_position", 0))
                    if resume_position:
                        records = records[resume_position:]
                    selected = {
                        **selected,
                        "resume_position": len(records) + resume_position,
                    }
                    prompts.append(
                        "Extract actionable observations as JSON "
                        "from this session digest:\n" + build_digest(records, 12_000)
                    )
                    prompt_rows.append((selected, metrics))
            except Exception as error:  # noqa: BLE001
                output.update(status="failed", reason=str(error)[:200])
                if not options["no_model"]:
                    mark_review_row(
                        options["store"],
                        {
                            **row,
                            "status": "failed",
                            "reason": str(error),
                            "run_at": options["run_at"],
                        },
                        latest_by_key=index,
                    )
        results.setdefault(key, {"output": output})
    return observations, results, prompts, prompt_rows, spend_sessions


def _open_friction(store: Path) -> list[Mapping[str, Any]]:
    log = open_repository(store).event_log()
    state, grouped = log.state, log.grouped_occurrences
    return [
        {
            "title": item.title,
            "status": item.status,
            "occurrences": [item.evidence for item in grouped.get(item.event_id, [])],
        }
        for item in state.items
        if item.status == "open"
    ]


def _finding_cwd(finding: Mapping[str, Any], sessions: list[dict[str, Any]]) -> Path:
    evidence = finding.get("evidence", [])
    references = evidence if isinstance(evidence, list) else []
    for reference in references:
        if not isinstance(reference, dict):
            continue
        session_id = reference.get("session_id")
        harness = reference.get("harness")
        match = next(
            (
                row
                for row in sessions
                if row.get("session_id") == session_id
                and row.get("harness") == harness
                and row.get("cwd")
            ),
            None,
        )
        if match:
            return Path(match["cwd"])
    return Path("/")


def _add_friction_candidates(
    store: Path,
    candidates: list[dict[str, Any]],
    findings: dict[str, list[dict[str, Any]]],
    sessions: list[dict[str, Any]],
) -> tuple[int, int]:
    failures = 0

    def add_candidates(repository):
        from ..store import write as store_write
        from ..store.types import FrictionAddMode, FrictionAddRequest

        nonlocal failures
        for candidate in candidates:
            finding = next(
                finding
                for group in findings.values()
                for finding in group
                if str(candidate["title"])
                == str(finding.get("title", "Untitled finding"))
            )
            cwd = _finding_cwd(finding, sessions)
            if not cwd.is_dir():
                cwd = store
            try:
                store_write.add_friction(
                    repository,
                    FrictionAddRequest(
                        FrictionAddMode.create(
                            "varde learn run", str(candidate["title"]), None, False
                        ),
                        str(candidate["evidence"]),
                        cwd,
                    ),
                )
            except Exception:  # noqa: BLE001 - each finding is independent
                failures += 1
        return len(candidates) - failures

    from ..cli_friction_write import _with_write_store

    added = _with_write_store(add_candidates, store)
    return added, failures


def run_review(
    *,
    window: str = "yesterday",
    budget_tokens: int | None = None,
    no_model: bool = False,
    dry_run: bool = False,
    runner: Runner = subprocess.run,
    store_dir: Path | None = None,
) -> dict[str, Any]:
    store = store_dir or resolve_store_dir()
    if dry_run:
        return _run_review_locked(
            window=window,
            budget_tokens=budget_tokens,
            no_model=no_model,
            dry_run=True,
            runner=runner,
            store_dir=store,
        )
    try:
        with file_lock(store / "review.lock", timeout=0):
            return _run_review_locked(
                window=window,
                budget_tokens=budget_tokens,
                no_model=no_model,
                dry_run=dry_run,
                runner=runner,
                store_dir=store,
            )
    except Locked as error:
        raise RuntimeError("a learn review is already running") from error


def _extract_prompts(
    work: dict[str, Any], budget: Budget, settings: dict[str, Any], runner: Runner
) -> tuple[int, float | None, bool, str | None, str | None]:
    batch = extract_batch(
        work["prompts"],
        budget=budget,
        model_id=str(settings["model_id"]),
        runner=runner,
    )
    costs = []
    tokens = 0
    for (row, metrics), result in zip(work["prompt_rows"], batch.results, strict=False):
        key = (row["harness"], row["session_id"])
        tokens += result.tokens
        if result.cost_usd is not None:
            costs.append(result.cost_usd)
        work["observations"].append(
            {
                "harness": row["harness"],
                "session_id": row["session_id"],
                "metrics": metrics,
                "observation": result.text or "",
            }
        )
        work["session_results"][key] = {
            "row": row,
            "metrics": metrics,
            "status": "analyzed" if result.status == "ok" else result.status,
            "reason": result.error,
            "tokens": result.tokens,
        }
    for row, _metrics in work["prompt_rows"][len(batch.results) :]:
        if batch.stop_reason == "rate_limited":
            reason = "rate_limited"
        elif batch.stop_reason == "budget_exhausted":
            reason = "budget"
        else:
            reason = batch.stop_reason or "budget"
        work["session_results"][(row["harness"], row["session_id"])] = {
            "row": row,
            "status": "pending",
            "reason": reason,
        }
    return (
        tokens,
        sum(costs) if costs else None,
        batch.stop_reason == "budget_exhausted",
        batch.stop_reason,
        batch.stop_error,
    )


def _prepare_inventory(
    store: Path, interval: tuple[datetime, datetime], dry_run: bool, no_model: bool
) -> tuple[
    list[Any],
    Any,
    list[dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    list[dict[str, Any]],
]:
    locations = load_locations()
    if not dry_run and not no_model:
        write_imported(store, analyzed.read_all(store))
    index = read_index(store)
    pending_paths = {
        str(Path(str(row.get("path"))).resolve(strict=False))
        for row in index.values()
        if row.get("status") in {"pending", "rate_limited"} and row.get("path")
    }
    inventory = build_inventory(locations, interval, pending_paths)
    rows = inventory.sessions
    for row in rows:
        key = (row["harness"], row["session_id"])
        if row.get("status") == "skipped: out of window" and index.get(key, {}).get(
            "status"
        ) in {"pending", "rate_limited"}:
            row.update(status="analyzable", reason="pending session")
        if row.get("status") != "analyzable":
            continue
        try:
            row["fingerprint"] = fingerprint(
                row["path"].partition("#")[0], row["session_id"]
            )
        except (OSError, ValueError) as error:
            row["fingerprint_error"] = str(error)
    pending = select_pending(
        [row for row in rows if row.get("status") == "analyzable"],
        list(index.values()),
    )
    return locations, inventory, rows, index, pending


def _synthesize_observations(
    observations: list[Mapping[str, Any]],
    store: Path,
    budget: Budget,
    settings: dict[str, Any],
    runner: Runner,
) -> tuple[dict[str, list[dict[str, Any]]], int, float | None, bool, str, str | None]:
    findings, result = synthesize(
        observations,
        _open_friction(store),
        budget=budget,
        model_id=str(settings["model_id"]),
        runner=runner,
    )
    return (
        findings,
        result.tokens,
        result.cost_usd,
        result.status == "budget_exhausted",
        result.status,
        result.error,
    )


def _persist_session_results(
    store: Path,
    index: dict[tuple[str, str], dict[str, Any]],
    results: dict[tuple[str, str], dict[str, Any]],
    run_at: str,
) -> None:
    for result in results.values():
        row = result.get("row")
        if not row or result.get("status") == "pending":
            continue
        mark_review_row(
            store,
            {
                **row,
                "status": result.get("status", "analyzed"),
                "reason": result.get("reason"),
                "metrics": result.get("metrics"),
                "fingerprint": row.get("fingerprint"),
                "run_at": run_at,
                "source": "review",
            },
            latest_by_key=index,
        )


def _location_rows(
    locations: list[Any], statuses: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result = [
        {
            "harness": row.harness,
            "path": str(row.path),
            "origin": row.origin,
            "status": row.status,
            "reason": row.reason,
        }
        for row in locations
    ]
    for status in statuses:
        if status.get("status") in {"missing", "unreadable"}:
            continue
        harness = next(
            (row.harness for row in locations if str(row.path) == status.get("root")),
            "unknown",
        )
        result.append({"harness": harness, **status})
    return result


def _session_results(
    rows: list[dict[str, Any]], results: dict[tuple[str, str], dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sessions = []
    for row in rows:
        key = (row["harness"], row["session_id"])
        current = results.get(key, {})
        output = current.get("output") or {
            key: row.get(key)
            for key in ("harness", "session_id", "kind", "parent_id", "cwd", "project")
        }
        output.update(
            status=current.get("status", output.get("status", "skipped")),
            reason=current.get("reason", output.get("reason")),
            tokens=current.get("tokens", 0),
        )
        sessions.append(output)
    counts = {
        status: sum(row["status"] == status for row in sessions)
        for status in ("analyzed", "skipped", "failed", "pending")
    }
    coverage = {
        "found": len(sessions),
        **counts,
        "by_harness": {
            harness: sum(row["harness"] == harness for row in sessions)
            for harness in sorted({row["harness"] for row in sessions})
        },
    }
    return sessions, coverage


def _run_review_locked(
    *,
    window: str = "yesterday",
    budget_tokens: int | None = None,
    no_model: bool = False,
    dry_run: bool = False,
    runner: Runner = subprocess.run,
    store_dir: Path | None = None,
) -> dict[str, Any]:
    store = store_dir or resolve_store_dir()
    now = datetime.now(UTC)
    interval = _window(window, store, now)
    locations, inventory, rows, index, pending = _prepare_inventory(
        store, interval, dry_run, no_model
    )
    run_at = now.isoformat()
    settings = review_config()
    config_budget = int(budget_tokens or settings["token_budget"])
    budget = Budget(
        config_budget,
        wall_clock_seconds=float(settings["wall_clock_seconds"]),
        synthesis_input_cap=int(settings.get("synthesis_input_cap", 20_000)),
    )
    observations, session_results, prompts, prompt_rows, spend_sessions = (
        _collect_sessions(
            rows,
            pending,
            index,
            {
                "dry_run": dry_run,
                "no_model": no_model,
                "store": store,
                "run_at": run_at,
                "window": interval,
            },
        )
    )
    model_tokens = 0
    cost = None
    exhausted = False
    stop_reason = None
    stop_error = None
    if not no_model and not dry_run and prompts:
        work = {
            "prompts": prompts,
            "prompt_rows": prompt_rows,
            "observations": observations,
            "session_results": session_results,
        }
        model_tokens, cost, exhausted, stop_reason, stop_error = _extract_prompts(
            work, budget, settings, runner
        )
    findings = {"setup": [], "project": []}
    if not dry_run and not no_model and observations:
        (
            findings,
            synthesis_tokens,
            synthesis_cost,
            synthesis_exhausted,
            synthesis_status,
            synthesis_error,
        ) = _synthesize_observations(observations, store, budget, settings, runner)
        model_tokens += synthesis_tokens
        if synthesis_cost is not None:
            cost = (cost or 0) + synthesis_cost
        exhausted = exhausted or synthesis_exhausted
        if synthesis_status in {"budget_exhausted", "rate_limited", "failed"}:
            stop_reason = synthesis_status
            stop_error = synthesis_error
    location_rows = _location_rows(locations, inventory.statuses)
    harnesses = [row.harness for row in locations]
    spend_data = spend.build(spend_sessions, harnesses, interval[0], interval[1])
    previous = spend.read_previous(store, now.date().isoformat())
    spend_comparison = compare(previous, spend_data["snapshot"])
    model_findings = {key: list(value) for key, value in findings.items()}
    for category in ("setup", "project"):
        findings[category].extend(spend_data["findings"][category])
    friction_added = 0
    friction_failed = 0
    report_path = None
    if not dry_run:
        report_path = str(
            write_report(
                store,
                now.date(),
                render_report(
                    findings,
                    run_date=now.date(),
                    locations=location_rows,
                    model_tokens=model_tokens,
                    cost_usd=cost,
                    token_spend=spend.render(spend_data, spend_comparison),
                ),
            )
        )
        spend.write_snapshot(store, now.date().isoformat(), spend_data["snapshot"])
    if not dry_run and model_findings != {"setup": [], "project": []}:
        existing_keys = {
            marker
            for event in open_repository(store).event_log().events
            if isinstance(event.body, OccurrenceAppended)
            for marker in event.body.evidence.split()
            if marker.startswith("review-key:")
        }
        candidates = friction_candidates(model_findings, existing_keys)
        friction_added, friction_failed = _add_friction_candidates(
            store, candidates, model_findings, rows
        )
    if not dry_run and not no_model:
        for result in session_results.values():
            if result.get("status") != "pending" or not result.get("row"):
                continue
            mark_review_row(
                store,
                {
                    **result["row"],
                    "status": "pending",
                    "reason": result.get("reason"),
                    "run_at": run_at,
                },
                latest_by_key=index,
            )
        _persist_session_results(store, index, session_results, run_at)
        mark_review_row(
            store,
            {
                "harness": "review",
                "session_id": run_at,
                "status": "complete",
                "source": "review",
                "run_at": run_at,
            },
            latest_by_key=index,
        )
    sessions, coverage = _session_results(rows, session_results)
    result = {
        "window": {
            "start": interval[0].isoformat(),
            "end": interval[1].isoformat(),
        },
        "run_at": run_at,
        "locations": location_rows,
        "coverage": coverage,
        "sessions": sessions,
        "findings": findings,
        "friction_added": friction_added,
        "friction_failed": friction_failed,
        "model_tokens": model_tokens,
        "cost_usd_estimate": cost,
        "budget_tokens": config_budget,
        "budget_exhausted": exhausted,
        "stop_reason": stop_reason,
        "stop_error": stop_error,
        "report_path": report_path,
    }
    return _redact_result_text(result)


def _redact_result_text(value: Any) -> Any:
    """Redact transcript-derived prose without changing structural values."""
    from .redact import redact

    if isinstance(value, list):
        return [_redact_result_text(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = dict(value)
    for key in ("reason", "title", "proposal"):
        if isinstance(result.get(key), str):
            result[key] = redact(result[key])
    for key in ("sessions", "locations", "findings"):
        if key in result:
            result[key] = _redact_result_text(result[key])
    return result
