"""Store and retrieve short progress lines outside plan artifacts."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, NoReturn

from varde_core.envelope import tool_error
from varde_learn.knowledge.cmdbase.output import for_code
from varde_learn.knowledge.frontmatter import parse
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.commands.status import (
    artifact_id,
    artifact_type,
    collect_plan_paths,
)
from varde_workflow.errors import InternalError
from varde_workflow.output import print_cli_success

MAX_LINE_CHARS = 200
_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9._-]+\Z", re.ASCII)


def _raise_invalid_now(message: str) -> NoReturn:
    raise ValueError(message)


def normalize_line(value: str) -> str:
    return " ".join(value.split())[:MAX_LINE_CHARS]


def plan_key(plans_dir: Path, plan_path: Path) -> str:
    root = plans_dir.resolve(strict=True)
    directory = plan_path.parent.resolve(strict=True)
    try:
        relative = directory.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"plan path must be inside {plans_dir}") from exc
    parts = []
    for component in relative.parts:
        if (
            not component
            or component in {".", ".."}
            or not _SAFE_COMPONENT.fullmatch(component)
        ):
            raise ValueError(
                f"plan path contains an unsafe key component `{component}`"
            )
        parts.append(component.replace("_", "_u"))
    if not parts:
        raise ValueError("plan path has an empty key")
    return "__".join(parts)


def read_plan_id(path: Path) -> str:
    mapping, _ = parse(path.read_bytes())
    if artifact_type(mapping) != "plan":
        raise ValueError(f"{path} is not a plan")
    return artifact_id(path, mapping)


def resolve_plan(argument: str | Path, cwd: Path, plans_dir: Path) -> Path:
    argument = Path(argument)
    if argument.name == "plan.md":
        path = argument if argument.is_absolute() else cwd / argument
        canonical = path.resolve(strict=True)
        if not canonical.is_relative_to(plans_dir.resolve(strict=True)):
            raise ValueError(f"plan path must be inside {plans_dir}")
        read_plan_id(path)
        return path
    paths: list[Path] = []
    skipped = [0]
    if plans_dir.is_dir():
        collect_plan_paths(plans_dir, paths, skipped)
    matches = []
    for path in paths:
        try:
            identifier = read_plan_id(path)
        except OSError, ValueError:
            continue
        directory_name = path.parent.name
        if directory_name == str(argument) or identifier == str(argument):
            matches.append(path)
    if not matches:
        raise ValueError(f"unknown plan `{argument}`")
    if len(matches) > 1:
        raise ValueError(f"plan id `{argument}` is ambiguous; pass a plan.md path")
    return matches[0]


def write_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(line.encode("utf-8") + b"\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise OSError(f"could not store now line at {path}: {exc}") from exc


def line_paths(plans_dir: Path, plan_path: Path) -> tuple[Path, Path]:
    key = plan_key(plans_dir, plan_path)
    working = plans_dir.parent
    return (
        working / ".cache" / "plan-now" / f"{key}.txt",
        working / "plan-now" / f"{key}.txt",
    )


def read_line(plans_dir: Path, plan_path: Path) -> str | None:
    try:
        current_path, legacy_path = line_paths(plans_dir, plan_path)
    except ValueError:
        return None
    for path in (current_path, legacy_path):
        try:
            value = path.read_text(encoding="utf-8")
            break
        except OSError:
            continue
    else:
        return None
    line = value.splitlines()[0].strip() if value.splitlines() else ""
    return line or None


def run(args: Any) -> int:
    try:
        cwd = Path.cwd()
        working = MemoryPaths.resolve(cwd).working.path
        plans_dir = working / "plans"
        plan_path = resolve_plan(args.plan, cwd, plans_dir)
        identifier = read_plan_id(plan_path)
        now_path, legacy_path = line_paths(plans_dir, plan_path)
        provided = [
            bool(getattr(args, "clear", False)),
            getattr(args, "text", None) is not None,
            getattr(args, "waiting", None) is not None,
        ]
        if sum(provided) != 1:
            _raise_invalid_now("provide exactly one of TEXT, --waiting, or --clear")
        if args.clear:
            now_path.unlink(missing_ok=True)
            legacy_path.unlink(missing_ok=True)
            result = {"plan": identifier, "cleared": True}
            message = f"Cleared now line for {identifier}."
        else:
            raw = (
                f"waiting: {args.waiting}"
                if args.waiting is not None
                else args.text or ""
            )
            line = normalize_line(raw)
            if not line:
                _raise_invalid_now(
                    "--waiting must contain non-whitespace text"
                    if args.waiting is not None
                    else "TEXT must contain non-whitespace text"
                )
            write_line(now_path, line)
            result = {"plan": identifier, "now": line}
            message = f"Set now line for {identifier}."
        if args.json:
            print_cli_success(result)
        else:
            print(message)
    except Exception as exc:
        error = InternalError(str(exc))
        if getattr(args, "json", False):
            envelope = tool_error(error.error_code(), str(error))
            data = envelope["data"]
            if not isinstance(data, dict):
                raise AssertionError("tool error data must be a mapping") from None
            error_data = data["error"]
            if not isinstance(error_data, dict):
                raise AssertionError("tool error details must be a mapping") from None
            error_data["fix"] = for_code(error.error_code()).as_value()
            print(
                json.dumps(
                    envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ),
                file=sys.stderr,
            )
        else:
            print(f"error: {error}", file=sys.stderr)
        return 1
    else:
        return 0
