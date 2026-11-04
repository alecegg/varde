"""Record an answer to an open question in a plan."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from varde_data.errors import DataError
from varde_learn.knowledge.frontmatter import parse
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.commands import status
from varde_workflow.output import print_cli_success


def answer_question(text: str, question: str, answer: str, date: str) -> str:
    """Remove one open question and append its dated decision."""
    answer_line = re.sub(r"\s+", " ", answer).strip().lstrip("#").strip()
    lines = text.splitlines()
    recorded = status.section_span(text, "decisions so far")
    decision_lines = _decision_lines(lines, recorded)
    already_recorded = any(
        line[2:].split(" → ", 1)[0] == question for line in decision_lines
    )
    if already_recorded and not question.isdigit():
        return text
    span = status.section_span(text, "open questions")
    if span is None:
        raise ValueError("plan has no Open Questions section")
    start, end = span
    bullets = status.section_bullets(lines, start, end)
    exact_matches = [item for item in bullets if item[2] == question]
    if exact_matches:
        if already_recorded:
            return text
        matches = exact_matches
    elif question.isdigit():
        index = int(question)
        matches = [bullets[index - 1]] if 1 <= index <= len(bullets) else []
    else:
        matches = []
    if not matches:
        raise ValueError(f"no open question matches {question!r}")
    if len(matches) > 1:
        raise ValueError(f"question {question!r} matches several open questions")
    first, last, bullet = matches[0]
    decision = f"- {bullet} → {answer_line} ({date})"
    decisions = recorded
    del lines[first:last]
    updated_text = "\n".join(lines)
    new_span = status.section_span(updated_text, "open questions")
    if new_span is not None and not status.section_bullets(lines, *new_span):
        _insert_empty_questions_marker(lines, new_span[0])
    if decisions is None:
        insert_at = status.section_span("\n".join(lines), "open questions")
        insertion = insert_at[0] - 1 if insert_at else len(lines)
        lines[insertion:insertion] = ["## Decisions so far", "", decision, ""]
    else:
        updated_decisions = status.section_span("\n".join(lines), "decisions so far")
        if updated_decisions is None:
            raise ValueError("plan has no Decisions so far section")
        insertion = _append_position(lines, updated_decisions)
        if not any(
            line.strip() for line in lines[updated_decisions[0] : updated_decisions[1]]
        ):
            if insertion < len(lines) and not lines[insertion].strip():
                insertion += 1
            else:
                lines.insert(insertion, "")
                insertion += 1
        lines.insert(insertion, decision)
        if insertion + 1 < len(lines) and lines[insertion + 1].startswith("#"):
            lines.insert(insertion + 1, "")
    result = "\n".join(lines)
    return result + ("\n" if text.endswith("\n") else "")


def _append_position(lines: list[str], span: tuple[int, int]) -> int:
    _, end = span
    while end > span[0] and not lines[end - 1].strip():
        end -= 1
    return end


def _insert_empty_questions_marker(lines: list[str], start: int) -> None:
    if start < len(lines) and not lines[start].strip():
        insertion = start + 1
        lines[insertion:insertion] = ["n/a — no open questions", ""]
        return
    lines[start:start] = ["", "n/a — no open questions", ""]


def _decision_lines(lines: list[str], span: tuple[int, int] | None) -> list[str]:
    if span is None:
        return []
    start, end = span
    return [line for line in lines[start:end] if line.startswith(("- ", "* "))]


def replace_body_bytes(raw: bytes, old_body: bytes, new_body: bytes) -> bytes:
    """Replace the parsed body, which is a suffix after frontmatter parsing."""
    return raw[: len(raw) - len(old_body)] + new_body


def _resolve_plan(argument: str, cwd: Path, plans_dir: Path) -> Path:
    direct = Path(argument)
    if not direct.is_absolute():
        direct = cwd / direct
    if direct.is_file():
        plan = direct.resolve()
        if plan.name != "plan.md":
            raise ValueError("plan path must name plan.md")
        return plan
    paths: list[Path] = []
    status.collect_plan_paths(plans_dir, paths, [0])
    matches = []
    for path in paths:
        if path.name != "plan.md":
            continue
        try:
            mapping, _ = parse(path.read_bytes())
        except OSError, ValueError:
            continue
        identifier = status.artifact_id(path, mapping)
        if identifier == argument:
            matches.append(path.resolve())
    if len(matches) != 1:
        raise ValueError(f"plan id {argument!r} resolved to {len(matches)} plans")
    return matches[0]


def run(args: Any) -> int:
    try:
        cwd = Path.cwd()
        working = MemoryPaths.resolve(cwd).working.path
        plan = _resolve_plan(args.plan, cwd, working / "plans")
        from varde_workflow.commands.plan_write_errors import plan_repository

        repo = plan_repository(working, plan)
        record = repo.get_by_path(str(plan))
        raw = record.raw
        _, body = parse(raw)
        updated = answer_question(
            body, args.question, args.answer, date.today().isoformat()
        )
        changed = updated != body
        if changed:
            repo.replace_body(record, updated.encode())
        result = {
            "plan": str(plan),
            "question": args.question,
            "updated": changed,
        }
    except (DataError, OSError, ValueError) as exc:
        from varde_workflow.commands.plan_write_errors import (
            report_plan_write_exception,
        )

        return report_plan_write_exception(
            exc, getattr(args, "json", False), (OSError, ValueError)
        )
    else:
        if args.json:
            print_cli_success(result)
        else:
            message = (
                "Answered question in" if changed else "Question already answered in"
            )
            print(f"{message} {plan}.")
        return 0
