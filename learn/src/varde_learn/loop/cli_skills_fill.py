"""`varde learn skills fill <skill>`: record or retire a baseline gap fill."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from varde_core.envelope import success, tool_error

from varde_learn.docs import baseline_cmd
from varde_learn.docs.flow.scan import text_tokens

from .help import help_text
from .improve import fill

_VALUES = {
    "--baselines": "baselines",
    "--gen": "gen",
    "--step": "step",
    "--path": "path",
    "--form": "form",
    "--commit": "commit",
    "--tokens-added": "tokens_added",
    "--source": "source",
    "--window": "window",
    "--suspected-skips": "suspected_skips",
    "--how-requests": "how_requests",
    "--retire": "retire",
}
_FLAGS = ("--json", "--history")
_USAGE = (
    "usage: skills fill <skill> --baselines <dir> (--step <step> | --path <path>) "
    "--evidence <friction id>... --form text|how-line | --retire <id|all> | --history"
)


def run(args: list[str], io: object | None = None) -> int:
    if any(arg in {"-h", "--help"} for arg in args):
        _write(io, help_text("skills fill"))
        return 0
    as_json = "--json" in args
    history = "--history" in args
    parsed = _parse([arg for arg in args if arg not in _FLAGS])
    if parsed is None:
        return _fail(_USAGE, as_json, io)
    skill, options, evidence_ids = parsed
    try:
        manifest = baseline_cmd.find_manifest(Path(options["baselines"]))
        changelog = manifest.parent / "changelog.jsonl"
        lines = baseline_cmd.read_changelog(changelog)
        if history:
            return _show_history(skill, lines, changelog, as_json, io)
        gen = options.get("gen") or _newest_gen(manifest, skill)
        new = _new_lines(skill, gen, options, evidence_ids, manifest, lines)
        fill.append_lines(changelog, new)
    except (fill.FillError, baseline_cmd.BaselineError, OSError, ValueError) as error:
        return _fail(str(error), as_json, io)
    ids = [str(line["id"]) for line in new]
    if as_json:
        data = {"ids": ids, "changelog": str(changelog)}
        body = json.dumps(success(data, {"truncated": False}), separators=(",", ":"))
        _write(io, body + "\n")
    else:
        verb = "retired" if "retire" in options else "recorded"
        _write(io, f"{verb} {', '.join(ids)} in {changelog}\n")
    return 0


def _show_history(
    skill: str, lines: list[dict], changelog: Path, as_json: bool, io: object | None
) -> int:
    rows = fill.history(lines, skill)
    if as_json:
        data = {"fills": rows, "changelog": str(changelog)}
        body = json.dumps(success(data, {"truncated": False}), separators=(",", ":"))
        _write(io, body + "\n")
    else:
        _write(io, fill.format_history(rows))
    return 0


def _parse(args: list[str]) -> tuple[str, dict[str, str], list[str]] | None:
    options: dict[str, str] = {}
    evidence: list[str] = []
    operands: list[str] = []
    queue = list(args)
    while queue:
        arg = queue.pop(0)
        if arg in _VALUES and queue:
            options[_VALUES[arg]] = queue.pop(0)
        elif arg == "--evidence" and queue:
            evidence.append(queue.pop(0))
        elif arg.startswith("-"):
            return None
        else:
            operands.append(arg)
    if len(operands) != 1 or "baselines" not in options:
        return None
    return operands[0], options, evidence


def _newest_gen(manifest: Path, skill: str) -> str:
    skills = baseline_cmd.read_json(manifest).get("skills") or {}
    entries = (skills.get(skill) or {}).get("baselines") or []
    if not entries:
        raise fill.FillError(f"no baseline entry for {skill}; pass --gen")
    return str(entries[-1]["gen"])


def _new_lines(
    skill: str,
    gen: str,
    options: dict[str, str],
    evidence_ids: list[str],
    manifest: Path,
    lines: list[dict],
) -> list[dict]:
    if "retire" in options:
        only = None if options["retire"] == "all" else options["retire"]
        retired = fill.retire_lines(lines, skill, gen, only, _today())
        if not retired:
            raise fill.FillError(f"no active fill for {skill} in {gen}")
        return retired
    target = {key: options[key] for key in ("step", "path") if key in options}
    source = Path(options["source"]) if "source" in options else None
    commit = options.get("commit") or (
        baseline_cmd.head_commit(source) if source else None
    )
    if not commit:
        raise fill.FillError(
            "pass --commit or --source (the checkout to take HEAD from)"
        )
    tokens = _tokens_added(options, target, skill, gen, manifest, source)
    evidence = {
        "friction": evidence_ids,
        "demand_window": options.get("window", ""),
        "suspected_skips": int(options.get("suspected_skips", 0)),
        "how_requests": int(options.get("how_requests", 0)),
    }
    facts = {
        "commit": commit,
        "date": _today(),
        "supersedes": fill.superseded_id(lines, skill, target),
        "tokens_added": tokens,
        "evidence": evidence,
    }
    line = fill.build_fill(
        fill.next_id(lines, gen), skill, gen, target, options.get("form", ""), facts
    )
    return [line]


def _tokens_added(
    options: dict[str, str],
    target: dict[str, str],
    skill: str,
    gen: str,
    manifest: Path,
    source: Path | None,
) -> int:
    """Token growth of the filled file (SKILL.md for a step) against its slim copy."""
    if "tokens_added" in options:
        return int(options["tokens_added"])
    if source is None:
        raise fill.FillError("pass --tokens-added or --source (to measure the file)")
    rel = target.get("path", "SKILL.md")
    ref = f"{skill}/{rel.removeprefix(f'{skill}/')}"
    current = baseline_cmd.current_files(baseline_cmd.source_packages(source))
    now = current.get(ref)
    if now is None:
        raise fill.FillError(f"{ref} not found under {source}")
    old = baseline_cmd.baseline_text(manifest, gen, ref) or ""
    return max(0, text_tokens(now[1]) - text_tokens(old))


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _fail(message: str, as_json: bool, io: object | None) -> int:
    if as_json:
        body = json.dumps(
            tool_error("skills_fill_failed", message), separators=(",", ":")
        )
        _write(io, body + "\n", error=True)
    else:
        _write(io, f"error: {message}\n", error=True)
    return 2


def _write(io: object | None, text: str, *, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    print(text, end="", file=stream or (sys.stderr if error else sys.stdout))
