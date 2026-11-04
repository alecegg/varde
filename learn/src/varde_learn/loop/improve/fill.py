"""Gap-fill records in a generation's `changelog.jsonl` (append-only).

A fill (stored next to MANIFEST.json) names a step or a path restored after a
baseline, with the friction ids and demand numbers that justified it.
Retiring appends a line with the same `id`, `status: retired` and `retired_at`;
readers take the last line per id. Nothing deletes or rewrites these lines
(reset, accept and baseline recording never touch the changelog), so every
fill stays listed by `history`. A fill that re-adds a retired step or path
carries `supersedes`, the earlier fill id.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

FORMS = ("text", "how-line")


class FillError(ValueError):
    """The fill or retire request cannot be recorded."""


def next_id(lines: Iterable[Mapping[str, object]], gen: str) -> str:
    taken = {
        str(line.get("id"))
        for line in lines
        if line.get("kind") == "fill" and line.get("gen") == gen
    }
    number = len(taken) + 1
    while f"fl-{gen}-{number:03d}" in taken:
        number += 1
    return f"fl-{gen}-{number:03d}"


def build_fill(
    fill_id: str,
    skill: str,
    gen: str,
    target: Mapping[str, str],
    form: str,
    facts: Mapping[str, object],
) -> dict[str, object]:
    """One active fill line; `target` holds exactly one of `step` or `path`.

    `facts` carries `commit`, `date`, `tokens_added` and `evidence`.
    """
    if form not in FORMS:
        raise FillError(f"--form must be one of {', '.join(FORMS)}")
    if set(target) not in ({"step"}, {"path"}):
        raise FillError("name exactly one of --step or --path")
    evidence = facts.get("evidence")
    if not isinstance(evidence, Mapping) or not evidence.get("friction"):
        raise FillError("a fill needs evidence: at least one --evidence friction id")
    record = {
        "id": fill_id,
        "kind": "fill",
        "gen": gen,
        "skill": skill,
        **target,
        "form": form,
        "status": "active",
        "commit": facts["commit"],
        "date": facts["date"],
        "tokens_added": facts["tokens_added"],
        "evidence": dict(evidence),
    }
    if facts.get("supersedes"):
        record["supersedes"] = facts["supersedes"]
    return record


def retire_lines(
    lines: Iterable[Mapping[str, object]],
    skill: str,
    gen: str,
    only: str | None,
    today: str,
) -> list[dict[str, object]]:
    """Retired copies of the active fills of `skill` and `gen` (or one `only` id)."""
    active = [
        line
        for line in _latest(lines).values()
        if line.get("skill") == skill
        and line.get("gen") == gen
        and line.get("status") == "active"
        and only in (None, line.get("id"))
    ]
    if only is not None and not active:
        raise FillError(f"no active fill {only} for {skill} in {gen}")
    return [{**line, "status": "retired", "retired_at": today} for line in active]


def superseded_id(
    lines: Iterable[Mapping[str, object]], skill: str, target: Mapping[str, str]
) -> str | None:
    """Id of the latest retired fill of `skill` with the same step or path."""
    found = None
    for line in _latest(lines).values():
        same = line.get("skill") == skill and all(
            line.get(key) == value for key, value in target.items()
        )
        if same and line.get("status") == "retired":
            found = str(line["id"])
    return found


def history(
    lines: Iterable[Mapping[str, object]], skill: str
) -> list[dict[str, object]]:
    """Every fill of `skill` (active and retired, all generations), oldest first."""
    rows = []
    for line in _latest(lines).values():
        if line.get("skill") != skill:
            continue
        evidence = line.get("evidence")
        rows.append(
            {
                "id": line["id"],
                "gen": line.get("gen"),
                "step": line.get("step"),
                "path": line.get("path"),
                "evidence": evidence.get("friction", [])
                if isinstance(evidence, dict)
                else [],
                "commit": line.get("commit"),
                "tokens_added": line.get("tokens_added"),
                "added_at": line.get("date"),
                "state": line.get("status"),
                "retired_at": line.get("retired_at"),
                "supersedes": line.get("supersedes"),
            }
        )
    return rows


def format_history(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "no fills\n"
    out = []
    for row in rows:
        target = row["step"] or row["path"]
        tail = f" retired_at={row['retired_at']}" if row["retired_at"] else ""
        link = f" supersedes={row['supersedes']}" if row["supersedes"] else ""
        evidence = ",".join(str(item) for item in row["evidence"] or [])  # type: ignore[attr-defined]
        out.append(
            f"{row['id']} {row['state']} {target} commit={row['commit']} "
            f"tokens_added={row['tokens_added']} "
            f"added_at={row['added_at']}{tail}{link} evidence={evidence}\n"
        )
    return "".join(out)


def _latest(lines: Iterable[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    latest: dict[str, Mapping[str, object]] = {}
    for line in lines:
        if line.get("kind") == "fill":
            latest[str(line.get("id"))] = line
    return latest


def append_lines(path: Path, lines: Iterable[Mapping[str, object]]) -> None:
    text = "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    sep = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(existing + sep + text, encoding="utf-8")
