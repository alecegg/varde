"""Background-maintained SQLite plan snapshot for runner readers."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from varde_data.plans import open_indexed_plans
from varde_workflow.collectors import (
    CollectorFacts,
    GitFacts,
    WatchCache,
    collect_status,
    collect_watch,
    frame_events,
    gather_collector_facts,
    parse_stale_seconds,
)
from varde_workflow.git_facts import get_git_facts

from varde_runner.plans_repository import plans_backend

logger = logging.getLogger(__name__)
# A reconcile stats every indexed plan and task; keep that work off a short poll.
REFRESH_INTERVAL = 60.0
INITIAL_REFRESH_DELAY = 1.0
MAX_REFRESH_BACKOFF = 60.0


class PlanReads:
    """Serve collectors over the last successful background refresh."""

    def __init__(
        self, working: Path, repo: Path, environment: dict[str, str] | None = None
    ) -> None:
        self.working = working.resolve()
        self.repo = repo.resolve()
        self.enabled = plans_backend(environment) == "sqlite"
        self.index: Any | None = None
        self.facts: CollectorFacts | None = None
        self.generation = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.refreshed_at: float | None = None
        self.last_error: str | None = None
        self._error_log_at = 0.0
        self._refresh_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._failures = 0
        self._as_of: float | None = None
        self._git_facts: GitFacts | None = None
        self.source_errors: dict[str, str] = {}
        self._has_persisted_index = False

    def start(self) -> None:
        if not self.enabled:
            return
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._publish_persisted_index()
            self._thread = threading.Thread(
                target=self._run, name="varde-plans-refresh", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)
        if thread is None or not thread.is_alive():
            self._thread = None

    @property
    def ready(self) -> bool:
        with self._lock:
            return self.index is not None

    @property
    def has_persisted_index(self) -> bool:
        return self._has_persisted_index

    def snapshot_marker(self) -> dict[str, Any]:
        with self._lock:
            return {"ready": self.index is not None, "as_of": self._as_of}

    def refresh_once(self) -> None:
        """Refresh each source independently and retain its last good value."""
        if not self.enabled:
            return
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            self._refresh_index()
            self._refresh_facts()
        finally:
            self._refresh_lock.release()

    def _refresh_index(self) -> None:
        try:
            index = self.index or _open_index(self.working)
            generation = index.refresh()
        except Exception as exc:  # noqa: BLE001 - preserve last good plan index.
            self._record_error("plans_index", exc)
            return
        with self._lock:
            self.index = index
            self.generation = generation
            self._as_of = time.time()
            self.refreshed_at = self._as_of
            self.source_errors.pop("plans_index", None)
            self._sync_error_state()

    def _refresh_facts(self) -> None:
        git = self._git_facts
        try:
            git = get_git_facts(self.repo)
        except Exception as exc:  # noqa: BLE001 - refresh sources independently.
            self._record_error("git_facts", exc)
        else:
            self._git_facts = git
            with self._lock:
                self.source_errors.pop("git_facts", None)
                self._sync_error_state()
        if git is None:
            git = self.facts.git if self.facts is not None else _empty_facts().git
        previous = self.facts
        if previous is not None:
            with self._lock:
                self.facts = CollectorFacts(
                    git,
                    previous.messages,
                    previous.bindings,
                    previous.decision_titles,
                    previous.source_version,
                    previous.decision_signature,
                )
        try:
            facts = gather_collector_facts(self.working, git)
        except Exception as exc:  # noqa: BLE001 - preserve last good collector facts.
            self._record_error("collector_facts", exc)
            return
        with self._lock:
            self.facts = facts
            self.source_errors.pop("collector_facts", None)
            self._sync_error_state()

    def _record_error(self, source: str, error: BaseException) -> None:
        now = time.monotonic()
        with self._lock:
            first = source not in self.source_errors
            self.source_errors[source] = str(error) or type(error).__name__
            self._sync_error_state()
            self._failures += 1
        if first or now - self._error_log_at >= 60:
            logger.warning("Could not refresh runner %s", source, exc_info=error)
            self._error_log_at = now

    def _sync_error_state(self) -> None:
        self.last_error = (
            "; ".join(
                f"{source}: {message}"
                for source, message in sorted(self.source_errors.items())
            )
            or None
        )
        if not self.source_errors:
            self._failures = 0

    def _run(self) -> None:
        if self._stop.wait(INITIAL_REFRESH_DELAY):
            return
        failures = 0
        while not self._stop.is_set():
            try:
                self.refresh_once()
                failures = self._failures
                with self._lock:
                    if set(self.source_errors) == {"refresh_loop"}:
                        self.source_errors.clear()
                        self._sync_error_state()
            except BaseException as exc:  # noqa: BLE001 - keep the loop restartable.
                self._record_error("refresh_loop", exc)
                failures = self._failures
            delay = min(REFRESH_INTERVAL * (2 ** min(failures, 5)), MAX_REFRESH_BACKOFF)
            self._stop.wait(delay)

    def _publish_persisted_index(self) -> None:
        path = self.working / ".cache" / "plans-read-index.sqlite3"
        if not path.exists() or self.index is not None:
            return
        try:
            index = _open_index(self.working)
            with self._lock:
                self.index = index
                self.generation = index.generation()
                self._has_persisted_index = self.generation > 0
                self._as_of = time.time()
        except Exception as exc:  # noqa: BLE001 - startup must keep serving if index fails.
            self._record_error("plans_index", exc)

    def _snapshot(self) -> tuple[Any, CollectorFacts] | None:
        with self._lock:
            if self.index is None:
                return None
            facts = self.facts or _empty_facts()
            return self.index, facts

    def status(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        if snapshot is None:
            return {"plans": [], "more_count": 0, "backlog_count": 0, "skipped": 0}
        index, facts = snapshot
        return collect_status(index, facts, working=self.working, repo=self.repo)

    def watch(self, stale: str = "20m") -> dict[str, Any]:
        snapshot = self._snapshot()
        if snapshot is None:
            return {"events": []}
        index, facts = snapshot
        seconds = parse_stale_seconds(stale)
        now = time.time()
        plans = collect_watch(
            index,
            facts,
            now=now,
            threshold_secs=seconds,
            working=self.working,
            repo=self.repo,
        )
        events, _ = frame_events(plans, now, seconds, WatchCache())
        result = {"events": [event.to_json() for event in events]}
        if plans:
            result["plans"] = plans
        return result

    def assigned_plans(self) -> list[dict[str, Any]]:
        snapshot = self._snapshot()
        if snapshot is None:
            return []
        index, _ = snapshot
        return [
            {**_decode_fields(row.get("frontmatter_json")), "id": row.get("id")}
            for row in index.plan_rows()
            if row.get("assigned_to")
        ]

    def tasks_for_plan(self, plan_id: str) -> list[dict[str, Any]]:
        snapshot = self._snapshot()
        if snapshot is None or not plan_id:
            return []
        index, _ = snapshot
        plan = next(
            (row for row in index.plan_rows() if row.get("id") == plan_id), None
        )
        if plan is None:
            return []
        tasks = index.task_rows(str(plan["path"]))
        return [
            {
                **_decode_fields(row.get("frontmatter_json")),
                "id": row.get("id"),
                "status": row.get("status"),
                "status_at": row.get("status_at"),
            }
            for row in tasks
        ]

    def owner_for_plan(self, plan_id: str) -> str | None:
        snapshot = self._snapshot()
        if snapshot is None:
            return None
        index, _ = snapshot
        for row in index.plan_rows():
            if row.get("id") == plan_id and isinstance(row.get("owner"), str):
                return str(row["owner"])
        return None

    def list_records(self) -> tuple[Any, ...]:
        snapshot = self._snapshot()
        if snapshot is None:
            return ()
        index, _ = snapshot
        return tuple(index.list().records)

    def detail_records(self, plan_id: str) -> tuple[Any, tuple[Any, ...]] | None:
        snapshot = self._snapshot()
        if snapshot is None or not plan_id or Path(plan_id).name != plan_id:
            return None
        index, _ = snapshot
        rows = [
            row
            for row in index.plan_rows()
            if row.get("artifact_type") == "plan" and not row.get("archived")
        ]
        direct_path = self.working / "plans" / plan_id / "plan.md"
        matches = [row for row in rows if Path(str(row["path"])) == direct_path]
        if not matches:
            matches = [
                row for row in rows if Path(str(row["path"])).parent.name == plan_id
            ]
        if len(matches) != 1:
            return None
        path = Path(str(matches[0]["path"]))
        ancestors = []
        known_paths = {str(row["path"]) for row in rows}
        for parent in path.parent.parents:
            candidate = parent / "plan.md"
            if candidate == self.working / "plans" / "plan.md":
                break
            if str(candidate) in known_paths:
                ancestors.append(str(candidate))
        ancestors.reverse()
        records = index.records_by_paths((*ancestors, str(path)))
        record = records.get(str(path))
        if record is None:
            return None
        return record, tuple(records[item] for item in ancestors) + (record,)

    def bindings(self) -> list[dict[str, Any]]:
        snapshot = self._snapshot()
        if snapshot is None:
            return []
        _, facts = snapshot
        return [dict(row) for row in facts.bindings]

    def generation_value(self) -> int:
        with self._lock:
            facts_key = (
                (
                    self.facts.source_version,
                    self.facts.git.refs_signature,
                    tuple(sorted(self.facts.git.worktree_activity.items())),
                )
                if self.facts
                else ()
            )
            digest = hashlib.blake2b(repr(facts_key).encode(), digest_size=8).digest()
            return int.from_bytes(digest, "big") ^ self.generation


def _decode_fields(value: object) -> dict[str, Any]:
    try:
        fields = json.loads(value) if isinstance(value, str) else None
    except ValueError:
        return {}
    return fields if isinstance(fields, dict) else {}


def _open_index(working: Path) -> Any:
    return open_indexed_plans(working)


def _empty_facts() -> CollectorFacts:
    git = GitFacts((), {}, frozenset(), {}, {})
    return CollectorFacts(git, (), (), {}, ("", ""), ())
