"""CLI mapping for compare-and-swap plan writer failures."""

from pathlib import Path

from varde_data.config import load_data_config
from varde_data.errors import Conflict, DataError, Invalid, Locked, NotFound
from varde_data.open import open_data
from varde_data.repos.plans import PlanRepositoryReader

from varde_workflow.commands.error import CliError


def plan_repository(
    working: Path, plan_path: Path | str | None = None
) -> PlanRepositoryReader:
    """Open the repository rooted at the resolved plan's containing plans tree."""
    if plan_path is not None:
        source = Path(plan_path).absolute()
        plans_dir = next(
            (
                parent
                for parent in (source.parent, *source.parents)
                if parent.name == "plans"
            ),
            None,
        )
        if plans_dir is not None:
            working = plans_dir.parent
    return open_data(working, load_data_config()).plans


class PlanWriteCliError(CliError):
    """A data writer failure with a stable CLI code and retry guidance."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def error_code(self) -> str:
        return self.code


PLAN_CONFLICT_CODE = "plan_conflict"
PLAN_CONFLICT_MESSAGE = "plan changed while writing; reload it and retry"
PLAN_LOCKED_CODE = "plan_locked"
PLAN_LOCKED_MESSAGE = "plan is locked by another operation; retry shortly"


def map_plan_write_error(error: Exception) -> CliError | None:
    """Map repository errors while preserving legacy messages where applicable."""
    if isinstance(error, Conflict):
        return PlanWriteCliError(PLAN_CONFLICT_CODE, PLAN_CONFLICT_MESSAGE)
    if isinstance(error, Locked):
        return PlanWriteCliError(PLAN_LOCKED_CODE, PLAN_LOCKED_MESSAGE)
    if isinstance(error, NotFound):
        return CliError(str(error))
    if isinstance(error, Invalid):
        return CliError(str(error))
    return None


def report_plan_write_exception(
    error: Exception,
    json_output: bool,
    legacy_exceptions: tuple[type[Exception], ...],
) -> int:
    """Report writer or legacy command errors, re-raising unexpected failures."""
    from varde_workflow.commands.error import report_cli_error

    mapped = map_plan_write_error(error)
    if mapped is not None:
        return report_cli_error(mapped, json=json_output)
    if isinstance(error, DataError):
        mapped = CliError(str(error))
        return report_cli_error(mapped, json=json_output)
    if isinstance(error, legacy_exceptions):
        return report_cli_error(CliError(str(error)), json=json_output)
    raise error
