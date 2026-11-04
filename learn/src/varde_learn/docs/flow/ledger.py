"""Decision ledger parsing, hashing, validation, and scoring."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _splitlines(text: str) -> list[str]:
    return text.splitlines()


def _lines_hash(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _source_lines(root: Path, rel: str) -> list[str] | None:
    try:
        return _splitlines((root / rel).read_bytes().decode("utf-8"))
    except OSError, UnicodeDecodeError:
        return None


def _cited(decision: dict, root: Path) -> list[str] | None:
    lines = _source_lines(root, decision["source"])
    start, end = decision["line_start"], decision["line_end"]
    if lines is None or not (1 <= start <= end <= len(lines)):
        return None
    return lines[start - 1 : end]


def _moved(decision: dict, root: Path) -> tuple[int, int] | None:
    lines = _source_lines(root, decision["source"]) or []
    size = decision["line_end"] - decision["line_start"] + 1
    if size <= 0:
        return None
    for start in range(len(lines) - size + 1):
        if _lines_hash(lines[start : start + size]) == decision.get("hash"):
            return start + 1, start + size
    return None


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("decisions", "files"):
        if not isinstance(data.get(key), list):
            raise TypeError(f"ledger field {key!r} is missing or not a list")
    for decision in data["decisions"]:
        for key in ("id", "phase", "source"):
            if not isinstance(decision.get(key), str):
                raise TypeError(f"decision field {key!r} is missing or not a string")
        for key in ("line_start", "line_end"):
            if not isinstance(decision.get(key), int) or isinstance(
                decision.get(key), bool
            ):
                raise TypeError(f"decision field {key!r} is missing or not an integer")
        if not isinstance(decision.get("alternatives"), list):
            raise TypeError('decision field "alternatives" is missing or not a list')
    return data


def score(data: dict, route: str | None = None) -> dict:
    routes = data.get("routes", {})
    if route is not None and route not in routes:
        raise ValueError(f"ledger has no route '{route}'")
    wanted = set(routes[route]) if route is not None else None
    phases: dict[str, dict[str, int]] = {}
    count = 0
    for decision in data["decisions"]:
        if wanted is not None and decision["phase"] not in wanted:
            continue
        units, depth = decision.get("units"), decision.get("depth")
        if not isinstance(units, int) or not isinstance(depth, int):
            raise TypeError(f"{decision['id']}: units and depth must be integers")
        row = phases.setdefault(
            decision["phase"], {"decisions": 0, "branch_units": 0, "cognitive": 0}
        )
        row["decisions"] += 1
        row["branch_units"] += units
        row["cognitive"] += units * (1 + depth)
        count += 1
    branch = sum(row["branch_units"] for row in phases.values())
    cognitive = sum(row["cognitive"] for row in phases.values())
    return {
        "decisions": count,
        "branch_units": branch,
        "cyclomatic": 1 + branch,
        "cognitive": cognitive,
        "phases": phases,
    }


def validate(data: dict, root: Path) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for decision in data["decisions"]:
        ident = decision["id"]
        if ident in seen:
            found.append(f"{ident}: duplicate decision id")
        seen.add(ident)
        alternatives = len(decision["alternatives"])
        if alternatives < 2 or decision.get("units") != alternatives - 1:
            found.append(f"{ident}: units do not match alternatives - 1")
        if not isinstance(decision.get("depth"), int) or decision["depth"] < 0:
            found.append(f"{ident}: invalid depth")
        lines = _cited(decision, root)
        if lines is None:
            found.append(
                f"{ident}: {decision['source']} lines "
                f"{decision['line_start']}-{decision['line_end']} not found"
            )
        elif decision.get("hash") != _lines_hash(lines):
            found.append(f"{ident}: hash does not match cited lines")
    found.extend(
        f"file missing: {item['path']}"
        for item in data["files"]
        if not (root / item["path"]).is_file()
    )
    found.extend(
        "unresolved local call: "
        + json.dumps(call, sort_keys=True, ensure_ascii=True, separators=(", ", ": "))
        for call in data.get("unresolved_calls", [])
        if call.get("kind") != "external-boundary"
    )
    return found


def check(data: dict, root: Path) -> list[str]:
    found = []
    for decision in data["decisions"]:
        lines = _cited(decision, root)
        if lines is not None and decision.get("hash") == _lines_hash(lines):
            continue
        moved = _moved(decision, root)
        location = (
            f"moved to {decision['source']} lines {moved[0]}-{moved[1]}"
            if moved
            else "changed or vanished"
        )
        found.append(f"{decision['id']}: {location}")
    return found


def hash_ledger(data: dict, root: Path) -> int:
    for decision in data["decisions"]:
        lines = _cited(decision, root)
        if lines is None:
            raise ValueError(f"{decision['id']}: cited lines not found")
        decision["hash"] = _lines_hash(lines)
    return len(data["decisions"])


def run(
    action: str,
    ledger: Path,
    root: Path,
    *,
    route: str | None = None,
    json_output: bool = False,
) -> dict | list[str] | str | int:
    """Run one ledger action from plain parameters; hash rewrites the file."""
    data = _load(ledger)
    if action == "hash":
        count = hash_ledger(data, root)
        ledger.write_text(
            json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
        return count
    if action == "validate":
        return validate(data, root)
    if action == "check":
        return check(data, root)
    if action == "score":
        result = score(data, route)
        if json_output:
            return result
        out = (
            f"cyclomatic {result['cyclomatic']} cognitive {result['cognitive']} "
            f"decisions {result['decisions']} branch_units "
            f"{result['branch_units']}\n"
        )
        for name, row in result["phases"].items():
            out += (
                f"  {name}: {row['decisions']} decisions, "
                f"{row['branch_units']} units, cognitive {row['cognitive']}\n"
            )
        return out
    raise ValueError(f"unknown ledger action: {action}")
