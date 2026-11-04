"""Review verification and plan conclusion behavior."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from varde_data.config import load_data_config
from varde_data.errors import Conflict, DataError, Locked
from varde_data.open import open_data
from varde_data.queue import open_queue
from varde_data.records.plans import PlanRecord
from varde_data.repos.plans import PlanRepositoryReader
from varde_learn.knowledge.cmdbase.errors import ExitCode
from varde_learn.knowledge.frontmatter import parse

from varde_workflow.route_decision import (
    RouteDecision,
    append_route_decision,
    parse_route_tier,
    read_route_decisions,
)

from .review_structure import open_critical_or_high, review_structure

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Conclusion:
    id: str
    head: str


class ConcludeError(ValueError, ExitCode):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def error_code(self) -> str:
        return self.code


def conclude(
    directory: Path | str, merged: str | None = None, repo: Path | str | None = None
) -> Conclusion:
    directory = Path(directory)
    try:
        directory = directory.resolve(strict=True)
    except OSError as exc:
        raise _review(f"{directory}: {exc}") from exc
    plan = directory / "plan.md"
    plan_record, plan_load_error = _load_plan_record_before_review(plan)
    review_path = directory / "review.md"
    try:
        mapping, _ = parse(review_path.read_bytes())
    except (OSError, ValueError) as exc:
        if isinstance(exc, FileNotFoundError):
            exc = OSError("No such file or directory (os error 2)")
        raise _review(f"{review_path}: {exc}") from exc
    structure = review_structure(review_path, full=False)
    if structure:
        raise _review("; ".join(structure))
    verdict = mapping.get("verdict")
    if verdict != "approved":
        raise _review(
            f"review verdict is {verdict if isinstance(verdict, str) else 'missing'}"
        )
    open_findings = open_critical_or_high(review_path)
    if open_findings:
        raise _review(
            "approved review has open critical/high findings: "
            + ", ".join(open_findings)
        )
    head = mapping.get("head")
    if not isinstance(head, str):
        raise _review("review report has no head")

    repository = _repository_root(Path(repo) if repo is not None else Path.cwd())
    reviewed = _resolve_commit(repository, head)
    if reviewed is None:
        raise ConcludeError(
            "git_error", f"review commit {head} not found in {repository}"
        )
    merged_ref = merged or "HEAD"
    merged_commit = _resolve_commit(repository, merged_ref)
    if merged_commit is None:
        raise ConcludeError(
            "git_error", f"merged commit {merged_ref} not found in {repository}"
        )
    if merged_commit != reviewed:
        raise _review(
            f"merged commit {merged_commit} does not match reviewed head {reviewed}"
        )

    if plan.is_file():
        if plan_load_error is not None:
            raise _review(str(plan_load_error)) from plan_load_error
        if plan_record is None:
            raise _review(f"{plan}: could not load plan record")
        plans, record = plan_record
        artifact_id = _artifact_id(plan)
        _set_plan_completed(plan, plans, record)
        _append_route_decisions_safely(directory, verdict)
        _mark_concluded_address(directory, artifact_id)
    elif (directory / "task.md").is_file():
        artifact_id = _artifact_id(directory / "task.md")
        _append_route_decisions_safely(directory, verdict)
    else:
        raise _review(f"{directory} has no plan.md or task.md")
    return Conclusion(artifact_id, reviewed)


def _append_route_decisions_safely(directory: Path, verdict: object) -> None:
    try:
        _append_route_decisions(directory, verdict)
    except Exception as error:  # noqa: BLE001 - Route telemetry must not gate conclude.
        _LOGGER.warning("could not record route decisions for %s: %s", directory, error)


def _append_route_decisions(directory: Path, verdict: object) -> None:
    """Record each original builder task's routing and available outcomes."""
    plans_dir = next(
        (parent for parent in directory.parents if parent.name == "plans"), None
    )
    if plans_dir is None:
        return
    items = open_queue(plans_dir.parent).list(plan_dir=str(directory.resolve()))
    existing = read_route_decisions(directory / "notes" / "route-decisions.jsonl")
    recorded = {item.task_id for item in existing.decisions if item.task_id}
    for item in items:
        if item.role != "builder":
            continue
        if (item.extra or {}).get("kind") in {"fix", "review"}:
            continue
        extra = item.extra or {}
        inputs = extra.get("inputs")
        inputs = inputs if isinstance(inputs, dict) else {}
        if item.id in recorded:
            continue
        try:
            route_tier = parse_route_tier(inputs.get("route_tier"))
        except ValueError:
            continue
        decision = RouteDecision(
            route_tier=route_tier,
            reviewers=(
                _strings(inputs.get("reviewers")) if "reviewers" in inputs else None
            ),
            model=_string(inputs.get("model")),
            provider=_string(inputs.get("provider")),
            input_tokens=_optional_integer(inputs.get("input_tokens")),
            output_tokens=_optional_integer(inputs.get("output_tokens")),
            cost=_optional_number(inputs.get("cost")),
            review_verdict=verdict if isinstance(verdict, str) else None,
            pyright_errors=_optional_integer(inputs.get("pyright_errors")),
            baseline_failures=_optional_integer(inputs.get("baseline_failures")),
            retries=_optional_integer(inputs.get("retries")),
            review_findings=_optional_integer(inputs.get("review_findings")),
            task_id=item.id,
        )
        append_route_decision(directory / "notes" / "route-decisions.jsonl", decision)


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(entry for entry in value if isinstance(entry, str))


def _optional_integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_number(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _mark_concluded_address(directory: Path, address: str) -> None:
    plans_dir = next(
        (parent for parent in directory.parents if parent.name == "plans"), None
    )
    if plans_dir is not None:
        working = plans_dir.parent
        data = open_data(working, load_data_config())
        data.messages.mark_concluded(address)
        slots = data.addresses.slots()
        slot_addresses = {slot.slot for slot in slots}
        for slot in slots:
            slot_addresses.update(slot.aliases)
        if address not in slot_addresses:
            data.addresses.retire({address}, set(), datetime.now(UTC))


def unchecked_acceptance(body: str) -> bool | None:
    in_section = False
    found = False
    for line in body.splitlines():
        if line.strip() == "## Acceptance criteria":
            in_section = found = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.lstrip().startswith("- [ ]"):
            return True
    return False if found else None


def _review(message: str) -> ConcludeError:
    return ConcludeError("review_invalid", message)


def _repository_root(start: Path) -> Path:
    result = subprocess.run(  # noqa: S603 - Runs a fixed Git metadata query.
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],  # noqa: S607 - Git is resolved from PATH.
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ConcludeError("git_error", "not inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def _resolve_commit(repository: Path, reference: str) -> str | None:
    if not reference or reference.startswith("-"):
        return None
    result = subprocess.run(  # noqa: S603 - Resolves a validated reference with fixed Git argv.
        [  # noqa: S607 - Git is resolved from PATH.
            "git",
            "-C",
            str(repository),
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{reference}^{{commit}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else None


def _artifact_id(path: Path) -> str:
    try:
        mapping, _ = parse(path.read_bytes())
    except OSError, ValueError:
        mapping = {}
    artifact_id = mapping.get("id")
    if isinstance(artifact_id, str) and artifact_id:
        return artifact_id
    return path.parent.name if path.name == "plan.md" else path.stem or "plan"


def _load_plan_record(
    path: Path,
) -> tuple[PlanRepositoryReader, PlanRecord]:
    working = next(
        (parent.parent for parent in path.parent.parents if parent.name == "plans"),
        path.parent.parent,
    )
    try:
        plans = open_data(working, load_data_config()).plans
        return plans, plans.get_by_path(str(path))
    except (DataError, OSError, ValueError) as exc:
        raise _review(f"{path}: {exc}") from exc


def _load_plan_record_before_review(
    path: Path,
) -> tuple[tuple[PlanRepositoryReader, PlanRecord] | None, ConcludeError | None]:
    if not path.is_file():
        return None, None
    try:
        return _load_plan_record(path), None
    except ConcludeError as exc:
        return None, exc


def _set_plan_completed(
    path: Path, plans: PlanRepositoryReader, record: PlanRecord
) -> None:
    try:
        plans.set_plan_status(record, "completed")
    except (Conflict, Locked) as exc:
        from .commands.plan_write_errors import map_plan_write_error

        mapped = map_plan_write_error(exc)
        if mapped is None:
            raise AssertionError(
                "conflict and lock errors must have a CLI mapping"
            ) from None
        raise ConcludeError(mapped.error_code(), str(mapped)) from exc
    except DataError as exc:
        raise _review(f"{path}: {exc}") from exc
    except (OSError, ValueError) as exc:
        raise _review(f"{path}: {exc}") from exc
