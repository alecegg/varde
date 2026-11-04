"""`varde learn skills updates [<skill>]`: read-only state and packaged diff."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from varde_core import skill_props
from varde_core.envelope import success, tool_error

from .help import help_text
from .improve import skill_updates, tool_entry

VERB = "updates"


def run(
    args: list[str],
    io: object | None = None,
    roots: Sequence[Path] | None = None,
    sync: Path | None = None,
) -> int:
    if any(arg in {"-h", "--help"} for arg in args):
        _write(io, help_text(f"skills {VERB}"))
        return 0
    as_json = "--json" in args
    operands = [arg for arg in args if arg != "--json"]
    if len(operands) > 1 or any(arg.startswith("-") for arg in operands):
        return _fail(f"usage: skills {VERB} [<skill>] [--json]", as_json, io)
    try:
        skills_dir = sync or tool_entry.require_sync_target()
        if operands:
            data = _one(skills_dir, operands[0], roots)
        else:
            data = {"skills": _rows(skills_dir)}
    except (ValueError, OSError) as error:
        return _fail(str(error), as_json, io)
    _report(io, data, as_json=as_json)
    return 0


def _state(directory: Path) -> tuple[skill_props.Props, str]:
    props = skill_props.parse((directory / skill_props.SIDECAR).read_text())
    return props, skill_updates.classify(
        props, skill_props.tree_hash(skill_props.disk_tree(directory))
    )


def _rows(skills_dir: Path) -> list[dict[str, str]]:
    rows = []
    for directory in tool_entry.sync_skill_roots(skills_dir):
        props, state = _state(directory)
        rows.append(
            {
                "skill": directory.name,
                "state": state,
                "packaged_version": props.packaged_version,
                "pending_version": props.pending_version,
            }
        )
    return rows


def _one(skills_dir: Path, name: str, roots: Sequence[Path] | None) -> dict:
    directory = tool_entry.installed_skill(skills_dir, name)
    if directory is None:
        raise ValueError(f"skill not installed: {name}")
    _, state = _state(directory)
    packaged = _packaged_texts(name, roots or tool_entry.package_roots())
    local = _texts(skill_props.disk_tree(directory))
    return {
        "skill": name,
        "state": state,
        "diff": skill_updates.diff_to_packaged(local, packaged),
    }


def _texts(tree: dict[str, bytes]) -> dict[str, str]:
    return {path: data.decode("utf-8", "replace") for path, data in tree.items()}


def _packaged_texts(name: str, roots: Sequence[Path]) -> dict[str, str]:
    """The packaged files of one skill, laid out as the synced skill dir."""
    found: dict[str, str] = {}
    for root in roots:
        sources = (
            (root / "skills" / name, ""),
            (root / "how" / name, "how/"),
            (root / tool_entry.TOOLS_DIR / name, f"{tool_entry.TOOLS_DIR}/{name}/"),
        )
        for base, prefix in sources:
            found.update(_tree(base, prefix))
        rows = [row for row in tool_entry.load_registry(root) if row.skill == name]
        if rows:
            registry = f"{tool_entry.TOOLS_DIR}/{tool_entry.REGISTRY_NAME}"
            found[registry] = skill_props.render_registry(
                (row.skill, row.step, row.entry) for row in rows
            )
    return found


def _tree(base: Path, prefix: str) -> dict[str, str]:
    if not base.is_dir():
        return {}
    files = {}
    for path in sorted(base.rglob("*")):
        relative = path.relative_to(base).as_posix()
        if path.is_file() and skill_props.is_hashed_path(relative):
            files[prefix + relative] = path.read_text(
                encoding="utf-8", errors="replace"
            )
    return files


def _report(io: object | None, data: dict, *, as_json: bool) -> None:
    if as_json:
        body = success(data, {"truncated": False})
        _write(io, json.dumps(body, separators=(",", ":")) + "\n")
    elif "skills" in data:
        lines = [f"{row['skill']}  {row['state']}" for row in data["skills"]]
        _write(io, "".join(line + "\n" for line in lines))
    else:
        _write(
            io, data["diff"] or f"{data['skill']}: no differences ({data['state']})\n"
        )


def _fail(message: str, as_json: bool, io: object | None) -> int:
    if as_json:
        body = json.dumps(
            tool_error(f"skills_{VERB}_failed", message), separators=(",", ":")
        )
        _write(io, body + "\n", error=True)
    else:
        _write(io, f"error: {message}\n", error=True)
    return 2


def _write(io: object | None, text: str, *, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    print(text, end="", file=stream or (sys.stderr if error else sys.stdout))
