"""Read-only draft skeleton for distilling a plan."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_core.envelope import tool_error
from varde_learn.knowledge.cmdbase.output import for_code
from varde_learn.knowledge.frontmatter import parse
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.errors import InternalError


@dataclass(frozen=True)
class Draft:
    markdown: str
    data: dict[str, Any]


def run(args: Any) -> int:
    try:
        draft = distill(args.plan_dir)
    except FileNotFoundError:
        plan_path = Path(args.plan_dir) / "plan.md"
        return _report_error(
            InternalError(str(plan_path)), getattr(args, "json", False)
        )
    except (OSError, ValueError) as exc:
        return _report_error(InternalError(str(exc)), getattr(args, "json", False))
    if getattr(args, "json", False):
        from varde_workflow.output import print_cli_success

        print_cli_success(draft.data)
    else:
        print(draft.markdown, end="")
    return 0


def _report_error(error: InternalError, json_output: bool) -> int:
    if json_output:
        code = error.error_code()
        envelope = tool_error(code, str(error))
        data = envelope["data"]
        if not isinstance(data, dict):
            raise AssertionError("tool error data must be a mapping")
        error_data = data["error"]
        if not isinstance(error_data, dict):
            raise AssertionError("tool error details must be a mapping")
        error_data["fix"] = for_code(code).as_value()
        print(
            json.dumps(
                envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ),
            file=sys.stderr,
        )
    else:
        print(f"error: {error}", file=sys.stderr)
    return 1


def distill(argument: Path | str, cwd: Path | None = None) -> Draft:
    cwd = cwd or Path.cwd()
    memory = MemoryPaths.resolve(cwd)
    plan_dir = Path(argument)
    if not plan_dir.is_absolute():
        plan_dir = cwd / plan_dir
    plan_path = plan_dir / "plan.md"
    mapping, body = parse(plan_path.read_bytes())
    title = next(
        (line[2:] for line in body.splitlines() if line.startswith("# ")),
        plan_dir.name or "plan",
    )
    status = (
        mapping.get("status") if isinstance(mapping.get("status"), str) else "unknown"
    )
    tasks: list[str] = []
    tasks_dir = plan_dir / "tasks"
    if tasks_dir.is_dir():
        for entry in sorted(tasks_dir.iterdir()):
            if entry.suffix != ".md":
                continue
            task_meta, task_body = parse(entry.read_bytes())
            task_title = next(
                (line[2:] for line in task_body.splitlines() if line.startswith("# ")),
                entry.stem or "task",
            )
            task_status = (
                task_meta.get("status")
                if isinstance(task_meta.get("status"), str)
                else "unknown"
            )
            tasks.append(f"- {task_title} ({task_status})")
    review_path = plan_dir / "review.md"
    review = None
    if review_path.is_file():
        review_meta, _ = parse(review_path.read_bytes())
        review = (
            review_meta.get("verdict") or "unknown",
            review_meta.get("head") or "unknown",
        )
    files, byte_count = count_files(plan_dir)
    bundle = memory.working.path / "distilled"
    review_text = (
        f"- Verdict: {review[0]}\n- Head: {review[1]}" if review else "- No review.md"
    )
    markdown = (
        f"# {title}\n\nStatus: {status}\n\n## Problem\n\n{section(body, 'Problem')}\n\n"
        f"## Solution\n\n{section(body, 'Solution')}\n\n"
        f"## Decisions so far\n\n{section(body, 'Decisions so far')}\n\n"
        f"## Tasks\n\n{chr(10).join(tasks) if tasks else '(none)'}\n\n## Review\n\n"
        f"{review_text}\n\n"
        f"- reviewed_commit: {mapping.get('reviewed_commit', '')}\n"
        f"- Plan files: {files}\n- Plan bytes: {byte_count}\n"
        f"- Distilled bundle: {bundle}\n\n"
        "## Why\n\n## Lessons\n\n## Measurements\n\n"
    )
    data = {
        "title": title,
        "status": status,
        "reviewed_commit": mapping.get("reviewed_commit"),
        "review": {"verdict": review[0], "head": review[1]} if review else None,
        "files": files,
        "bytes": byte_count,
        "bundle_path": str(bundle),
        "markdown": markdown,
    }
    return Draft(markdown, data)


def section(body: str, heading: str) -> str:
    marker = f"## {heading}"
    start = body.find(marker)
    if start < 0:
        return "(not stated)"
    return body[start + len(marker) :].split("\n## ", 1)[0].strip()


def count_files(directory: Path) -> tuple[int, int]:
    count = total = 0
    for path in directory.rglob("*"):
        if path.is_file():
            count += 1
            total += path.stat().st_size
    return count, total
