"""CLI operations for the SQLite plan state store."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from varde_data.errors import Conflict, DataError
from varde_data.locking import atomic_write
from varde_data.plan_state_sync import export_plan_dir, import_plan_dir
from varde_data.queue_line_sync import export_line_queue, import_line_queue
from varde_data.queue_md import parse_queue_md
from varde_data.queue_migrate import MigrationReport, migrate, verify
from varde_data.queue_mode_lock import operation
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_rollback import rollback
from varde_data.queue_store import (
    create_backup,
    export_metadata,
    initialize,
    restore_backup,
    status,
)
from varde_data.queue_sync import (
    export_queue_md,
    import_queue_md,
    record_queue_md_export,
)
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.errors import InternalError, report_error
from varde_workflow.output import print_cli_success

_DATABASE = QUEUE_DATABASE


def run(args: Any) -> int:
    """Run one plan store operation and report errors in the normal CLI shape."""
    working = MemoryPaths.resolve(Path.cwd()).working.path
    try:
        result = _run_action(args, working)
    except (DataError, OSError, ValueError, sqlite3.Error) as error:
        return report_error(
            InternalError(str(error)), bool(getattr(args, "json", False))
        )
    if getattr(args, "json", False):
        print_cli_success(result)
    else:
        _print_result(args.store_action, result)
    return 0


def _run_action(args: Any, working: Path) -> dict[str, Any]:
    dry_run = bool(getattr(args, "dry_run", False))
    handlers = {
        "status": lambda: _status(working),
        "migrate": lambda: _migrate(working, dry_run),
        "import": lambda: _import(working, dry_run),
        "export": lambda: _export(working, dry_run),
        "backup": lambda: _backup(working, dry_run),
        "restore": lambda: _restore(working, args.backup, dry_run),
        "rollback": lambda: _rollback(working, dry_run),
        "verify": lambda: _verify(working),
    }
    try:
        return handlers[args.store_action]()
    except KeyError as error:
        raise ValueError(f"unknown store action: {args.store_action}") from error


def _migrate(working: Path, dry_run: bool) -> dict[str, Any]:
    database_existed = (working / _DATABASE).is_file()
    result = _record(migrate(working, dry_run=dry_run))
    if not dry_run and database_existed and result.get("backup") is None:
        raise Conflict("queue migration completed without a fresh backup")
    return result


def _backup(working: Path, dry_run: bool) -> dict[str, Any]:
    database = working / _DATABASE
    if dry_run:
        return {
            "dry_run": True,
            "database": str(database),
            "exists": database.is_file(),
        }
    return {"backup": str(create_backup(working))}


def _restore(working: Path, argument: str, dry_run: bool) -> dict[str, Any]:
    source = Path(argument).expanduser().resolve()
    if dry_run:
        if not source.is_file():
            raise FileNotFoundError(source)
        return {"dry_run": True, "backup": str(source)}
    return {"restored": str(restore_backup(working, source))}


def _rollback(working: Path, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        with operation(working):
            differences = verify(working)
        return {"dry_run": True, "differences": differences}
    report = rollback(working)
    if not report.backup.is_file():
        raise Conflict("queue rollback completed without a fresh backup")
    return {"backup": str(report.backup)}


def _verify(working: Path) -> dict[str, Any]:
    with operation(working):
        differences = verify(working)
    return {"differences": differences, "ok": not differences}


def _status(working: Path) -> dict[str, Any]:
    return status(working)


def _queue_files(working: Path) -> list[Path]:
    plans = working / "plans"
    return sorted(plans.rglob("queue.md")) if plans.is_dir() else []


def _plan_dirs(working: Path) -> list[Path]:
    plans = working / "plans"
    return (
        sorted(path.parent for path in plans.rglob("plan.md")) if plans.is_dir() else []
    )


def _import(working: Path, dry_run: bool) -> dict[str, Any]:
    queues = _queue_files(working)
    plans = _plan_dirs(working)
    if dry_run:
        return {
            "dry_run": True,
            "queues": [str(path) for path in queues],
            "plans": [str(path) for path in plans],
        }
    queue_reports: list[dict[str, Any]] = []
    skipped_task_states: list[str] = []
    with operation(working):
        initialize(working)
        for path in queues:
            text = path.read_text(encoding="utf-8")
            try:
                document = parse_queue_md(text)
            except ValueError:
                document = None
            if document is not None and document.header:
                report = import_queue_md(path, path.relative_to(working).as_posix())
            elif path.parent.name == "notes":
                report = import_line_queue(path.parent.parent)
            else:
                continue
            queue_reports.append({"path": str(path), **asdict(report)})
        for directory in plans:
            skipped_task_states.extend(import_plan_dir(working, directory))
    return {
        "queues": queue_reports,
        "plans_imported": [str(path) for path in plans],
        "skipped_task_states": skipped_task_states,
    }


def _export(working: Path, dry_run: bool) -> dict[str, Any]:
    database = working / _DATABASE
    if not database.is_file():
        raise Conflict("queue store database does not exist")
    with operation(working) as mode:
        if mode != "sqlite":
            raise Conflict("queue store is not in sqlite mode")
        queue_names, plan_dirs = export_metadata(working)
        targets = [_queue_path(working, name) for name in queue_names]
        targets.extend(_plan_path(working, path) for path in plan_dirs)
        if dry_run:
            return {"dry_run": True, "files": [str(path) for path in targets]}
        for queue_name in queue_names:
            path = _queue_path(working, queue_name)
            if queue_name.startswith("line:"):
                rendered = export_line_queue(path.parent.parent)
            else:
                import_queue_md(path, queue_name)
                rendered = export_queue_md(working, queue_name)
            atomic_write(
                path, rendered.encode("utf-8"), mode=path.stat().st_mode & 0o777
            )
            if not queue_name.startswith("line:"):
                record_queue_md_export(working, queue_name, rendered)
        for plan_dir in plan_dirs:
            import_plan_dir(working, _plan_path(working, plan_dir).parent)
            export_plan_dir(working, _plan_path(working, plan_dir).parent)
    return {"files": [str(path) for path in targets]}


def _queue_path(working: Path, queue_name: str) -> Path:
    relative = (
        queue_name.removeprefix("line:")
        if queue_name.startswith("line:")
        else queue_name
    )
    base = working.resolve()
    path = (base / relative).resolve()
    try:
        path.relative_to(base)
    except ValueError as error:
        raise ValueError(
            f"queue path escapes working directory: {queue_name}"
        ) from error
    return path / "notes" / "queue.md" if queue_name.startswith("line:") else path


def _plan_path(working: Path, plan_dir: Path) -> Path:
    path = plan_dir.resolve()
    try:
        path.relative_to((working / "plans").resolve())
    except ValueError as error:
        raise ValueError(f"plan path escapes working directory: {plan_dir}") from error
    return path / "plan.md"


def _record(value: MigrationReport) -> dict[str, Any]:
    result = asdict(value)
    return {
        key: str(item) if isinstance(item, Path) else item
        for key, item in result.items()
    }


def _print_result(action: str, result: dict[str, Any]) -> None:
    if action == "verify":
        if result["ok"]:
            print("Queue store verified; no differences.")
        else:
            print("Queue store differs from Markdown:")
            for difference in result["differences"]:
                print(f"- {difference}")
        return
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
