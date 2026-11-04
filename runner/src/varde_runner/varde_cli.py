"""Small subprocess boundary for the installed Varde CLI."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_data import Conflict
from varde_data.cache import CachedData
from varde_data.config import load_data_config
from varde_data.messages import record_send_liveness, touch_relay_wake
from varde_data.open import open_data
from varde_data.records.messages import NewMessage
from varde_data.records.plans import PlanRecord
from varde_data.repos.messages import MessageRepository
from varde_data.repos.plans import PlanRepositoryReader, resolve_plan_ref

from varde_runner.messages import message_dict
from varde_runner.plans_repository import shared_plans_repository

logger = logging.getLogger(__name__)


class VardeCLI:
    def __init__(
        self,
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.env = {**os.environ, **(env or {})}
        configured_working = self.env.get("VARDE_WORKING_DIR")
        if cwd is None:
            if not configured_working:
                raise ValueError("VardeCLI requires cwd or VARDE_WORKING_DIR")
            cwd = Path(configured_working).expanduser().resolve()
        self.cwd = cwd
        self.plan_reads: Any | None = None
        self._working_path: Path | None = None
        self._plans_lock = threading.Lock()
        self._plan_caches_lock = threading.Lock()
        self._repository: PlanRepositoryReader | None = None
        self._messages_repository: MessageRepository | None = None
        self._addresses_repository = None
        self._plan_caches: dict[
            bool,
            tuple[CachedData[tuple[PlanRecord, ...]], threading.Lock],
        ] = {}

    @property
    def _messages(self) -> MessageRepository:
        if self._messages_repository is not None:
            return self._messages_repository
        working_path = self._working_directory()
        if working_path is None:
            raise ValueError("Varde CLI did not return its working directory")
        repository = open_data(working_path, load_data_config()).messages
        self._messages_repository = repository
        return repository

    @property
    def _addresses(self):
        if self._addresses_repository is not None:
            return self._addresses_repository
        working_path = self._working_directory()
        if working_path is None:
            raise ValueError("Varde CLI did not return its working directory")
        repository = open_data(working_path, load_data_config()).addresses
        self._addresses_repository = repository
        return repository

    def _json(self, *args: str, timeout: float = 30) -> dict[str, Any]:
        result = subprocess.run(
            ["varde", *args, "--json"],
            cwd=self.cwd,
            env=self.env,
            capture_output=True,
            check=True,
            text=True,
            timeout=timeout,
        )
        value = json.loads(result.stdout)
        return value.get("data", value)

    def read_messages(self) -> list[dict[str, Any]]:
        return [message_dict(row) for row in self._messages.read_all().records]

    def read_message_status(self) -> dict[str, Any]:
        acked = {
            item.message_id: item.at
            for item in self._messages.deliveries()
            if item.event == "acked"
        }
        return {
            "messages": [
                {
                    **message_dict(message),
                    "acked": acked.get(message.id) if message.id is not None else None,
                }
                for message in self._messages.read_all().records
            ]
        }

    def acknowledge(self, message_id: str, *, address: str = "main") -> dict[str, Any]:
        result = subprocess.run(
            ["varde", "msg", "ack", message_id, "--as", address],
            cwd=self.cwd,
            env=self.env,
            capture_output=True,
            check=True,
            text=True,
        )
        return {"stdout": result.stdout, "message_id": message_id}

    def read_plan_status(self) -> dict[str, Any]:
        return self._json("plan", "status")

    def answer_plan_question(
        self, plan_id: str, question: str, answer: str
    ) -> dict[str, Any]:
        return self._json(
            "plan",
            "answer",
            plan_id,
            "--question",
            question,
            "--answer",
            answer,
            timeout=30,
        )

    def read_assigned_plans(self) -> list[dict[str, Any]]:
        working_path = self._working_directory()
        if working_path is None:
            logger.warning(
                "Cannot read assigned plans: no working directory is configured"
            )
            return []
        if not working_path.is_dir():
            logger.warning(
                "Cannot read assigned plans: working directory does not exist: %s",
                working_path,
            )
            return []
        plans = []
        # Invalid YAML is skipped by the shared repository, matching plan status.
        for record in self._list_plan_records(include_tasks=False):
            if record.artifact_type != "plan":
                continue
            fields = record.fields
            assigned_to = fields.get("assigned_to")
            if not assigned_to:
                continue
            plans.append(
                {
                    "id": fields.get("id") or record.id,
                    **fields,
                }
            )
        return plans

    def read_address_bindings(self) -> list[dict[str, Any]]:
        return [
            {
                "address": item.address,
                "session_id": item.session_id,
                "harness": item.harness,
                "bound_at": item.bound_at.isoformat(),
                "last_seen": item.last_seen.isoformat(),
                "token_id": item.token_id,
                **item.extra,
            }
            for item in self._addresses.list_bindings()
        ]

    def read_concluded_addresses(self) -> list[str]:
        return sorted(self._messages.concluded_addresses())

    def read_plan_graph(self, plan_id: str) -> dict[str, Any]:
        path = self._find_plan_path(plan_id)
        return self._json("plan", "graph", str(path), "--all")

    def read_plan_tasks(self, plan_id: str) -> list[dict[str, Any]]:
        plan = self._get_plan(plan_id)
        tasks = []
        for record in plan.tasks:
            fields = record.fields
            if fields.get("type") != "task":
                continue
            tasks.append(
                {
                    "id": fields.get("id") or Path(record.path).stem,
                    "title": fields.get("title", Path(record.path).stem),
                    "status": fields.get("status", "todo"),
                    **(
                        {"status_at": fields["status_at"]}
                        if fields.get("status_at")
                        else {}
                    ),
                    **({"owner": fields["owner"]} if fields.get("owner") else {}),
                }
            )
        return tasks

    def read_plan_summary(self, plan_id: str) -> dict[str, Any]:
        plan = self._get_plan(plan_id, include_tasks=False)
        fields = plan.fields
        return {
            "id": plan_id,
            "title": fields.get("title", plan_id),
            "status": fields.get("status", "unknown"),
            "owner": fields.get("owner"),
        }

    def _find_plan_path(self, plan_id: str) -> Path:
        if not plan_id or Path(plan_id).name != plan_id or plan_id in {".", ".."}:
            raise ValueError("plan_id must be a plain name")
        return Path(self._get_plan(plan_id, include_tasks=False).path)

    def _get_plan(self, plan_id: str, *, include_tasks: bool = True) -> PlanRecord:
        # The runner keeps its direct-path and basename precedence; shared lookup
        # handles the remaining id and date-suffix tiers without another list.
        records = tuple(
            record
            for record in self._list_plan_records(include_tasks=include_tasks)
            if record.artifact_type == "plan"
        )
        working_path = self._working_path
        if working_path is None:
            raise ValueError("Varde CLI did not return its working directory")
        direct = working_path / "plans" / plan_id / "plan.md"
        direct_match = next(
            (record for record in records if Path(record.path) == direct), None
        )
        if direct_match is not None:
            return direct_match

        basename_matches = tuple(
            record for record in records if Path(record.path).parent.name == plan_id
        )
        if len(basename_matches) == 1:
            return basename_matches[0]
        if len(basename_matches) > 1:
            raise FileNotFoundError(
                f"Could not uniquely find plan {plan_id!r}"
            ) from Conflict(f"plan reference {plan_id!r} is ambiguous")

        try:
            record = resolve_plan_ref(plan_id, records)
        except Conflict as error:
            raise FileNotFoundError(
                f"Could not uniquely find plan {plan_id!r}"
            ) from error
        if record is None:
            raise FileNotFoundError(
                f"Could not uniquely find plan {plan_id!r}"
            ) from None
        return record

    def _list_plan_records(self, *, include_tasks: bool) -> tuple[PlanRecord, ...]:
        repository = self._plans()
        refresh = getattr(repository, "refresh", None)
        if refresh is not None:
            refresh()
        with self._plan_caches_lock:
            entry = self._plan_caches.get(include_tasks)
            if entry is None:
                cache = CachedData(
                    lambda: repository.list(include_tasks=include_tasks).records,
                    repository.version,
                )
                entry = (cache, threading.Lock())
                self._plan_caches[include_tasks] = entry
        cache, cache_lock = entry
        with cache_lock:
            return cache.get()

    def _plans(self) -> PlanRepositoryReader:
        if self._repository is not None:
            return self._repository
        with self._plans_lock:
            if self._repository is not None:
                return self._repository
            working_path = self._resolve_working_directory()
            if working_path is None:
                raise ValueError("Varde CLI did not return its working directory")
            repository = shared_plans_repository(working_path, self.env)
            self._repository = repository
            return repository

    def _working_directory(self) -> Path | None:
        if self._working_path is not None:
            return self._working_path
        with self._plans_lock:
            return self._resolve_working_directory()

    def _resolve_working_directory(self) -> Path | None:
        if self._working_path is not None:
            return self._working_path
        working = self.env.get("VARDE_WORKING_DIR")
        if not working:
            working = self._json("setup", "paths").get("working")
        if not isinstance(working, str) or not working:
            return None
        self._working_path = Path(working).expanduser().resolve()
        return self._working_path

    def read_plan(self) -> dict[str, Any]:
        return self.read_plan_watch()

    def read_plan_watch(self, stale: str = "20m") -> dict[str, Any]:
        def load() -> dict[str, Any]:
            result = subprocess.run(
                [
                    "varde",
                    "plan",
                    "watch",
                    "--once",
                    "--no-inbox",
                    "--no-wake",
                    "--stale",
                    stale,
                    "--json",
                ],
                cwd=self.cwd,
                env=self.env,
                capture_output=True,
                check=True,
                text=True,
                timeout=120,
            )
            events = [json.loads(line) for line in result.stdout.splitlines() if line]
            plans = []
            if len(events) == 1 and "plans" in events[0] and "events" in events[0]:
                plans = events[0]["plans"]
                events = events[0]["events"]
            return {"events": events, **({"plans": plans} if plans else {})}

        return load()

    def send(
        self, *, sender: str, recipient: str, kind: str, text: str, notes: str
    ) -> dict[str, Any]:
        message = self._messages.append(
            NewMessage(
                from_=sender,
                to=recipient,
                kind=kind,
                text=text,
                notes=str(Path(notes).resolve()),
            )
        )
        working = self._working_directory()
        if working is not None:
            try:
                touch_relay_wake(working)
                record_send_liveness(
                    working, message.id or "", message.to, datetime.now(UTC)
                )
            except Exception:
                logger.debug("Could not record message send telemetry", exc_info=True)
        return {"stdout": "", "id": message.id}
