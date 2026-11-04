"""`varde learn skills report`: list loop records and write the report page."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from varde_core.envelope import success, tool_error

from varde_learn.memory import store

from .help import help_text
from .improve import record as rec
from .improve.report_page import build_page


def run(args: list[str], io: object | None = None) -> int:
    if any(arg in {"-h", "--help"} for arg in args):
        _write(io, help_text("skills report"))
        return 0
    as_json = "--json" in args
    rest = [arg for arg in args if arg != "--json"]
    if rest:
        return _fail(f"unexpected argument '{rest[0]}'", as_json, io)
    try:
        root = store.memory_root(Path.cwd())
        records, skipped = rec.scan_records(root)
        page = _write_page(root, records)
    except (rec.RecordError, OSError) as error:
        return _fail(str(error), as_json, io)
    for message in skipped:
        _write(io, f"warning: {message}\n", error=True)
    if as_json:
        data = {"records": [json.loads(rec.to_json(r)) for r in records], "page": page}
        if skipped:
            data["skipped"] = skipped
        _write(
            io,
            json.dumps(success(data, {"truncated": False}), separators=(",", ":"))
            + "\n",
        )
    else:
        _write(io, _table(records, page))
    return 0


def _write_page(root: Path, records: list[rec.LoopRecord]) -> str | None:
    open_proposals = [r for r in records if r.state == "proposed"]
    if not open_proposals:
        return None
    date = datetime.now(UTC).date().isoformat()
    pairs = [(r, rec.read_diff(root, r)) for r in open_proposals]
    path = rec.loop_dir(root) / "report" / f"{date}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_page(date, pairs))
    return str(path)


def _table(records: list[rec.LoopRecord], page: str | None) -> str:
    lines = [
        f"{r.id}  {r.skill}  {r.direction}  {r.state}  {r.token_delta:+d}"
        for r in records
    ]
    lines.append(
        f"report page: {page}" if page else "no open proposals; no report page written"
    )
    return "\n".join(lines) + "\n"


def _fail(message: str, as_json: bool, io: object | None) -> int:
    if as_json:
        _write(
            io,
            json.dumps(
                tool_error("skills_report_failed", message), separators=(",", ":")
            )
            + "\n",
            error=True,
        )
    else:
        _write(io, f"error: {message}\n", error=True)
    return 2


def _write(io: object | None, text: str, *, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    print(text, end="", file=stream or (sys.stderr if error else sys.stdout))
