"""Counted step tools: registry rows (pure) and the counting wrapper.

A tool is `<module root>/step_tools/<skill>/<step>.py` exposing
`run(args: list[str]) -> int`; `<module root>/step_tools/registry.toml` lists
one `[[tool]]` row per tool. The wrapper (`main`) runs a tool and appends the
counter row, so `learn skills demand` sees the call.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import time
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib.metadata import entry_points
from importlib.resources import files
from pathlib import Path

from varde_core import memory_dirs, skill_props

from varde_learn.loop import calls

TOOLS_DIR = "step_tools"
REGISTRY_NAME = "registry.toml"
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class ToolError(ValueError):
    """A registry row or tool lookup is invalid."""


@dataclass(frozen=True)
class ToolRow:
    skill: str
    step: str
    entry: str  # path under step_tools/, `<skill>/<step>.py`


def entry_for(skill: str, step: str) -> str:
    return f"{skill}/{step}.py"


def script_suffix(skill: str, step: str) -> str:
    """The path tail that identifies a tool script (used by bypass detection)."""
    return f"{TOOLS_DIR}/{entry_for(skill, step)}"


def validate_row(row: ToolRow) -> ToolRow:
    for label, value in (("skill", row.skill), ("step", row.step)):
        if not _NAME.match(value):
            raise ToolError(f"invalid {label}: {value!r}")
    if row.entry != entry_for(row.skill, row.step):
        raise ToolError(f"entry must be {entry_for(row.skill, row.step)}")
    return row


def parse_registry(text: str) -> list[ToolRow]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ToolError(f"invalid registry: {error}") from error
    rows = []
    for item in data.get("tool", []):
        try:
            rows.append(
                validate_row(ToolRow(item["skill"], item["step"], item["entry"]))
            )
        except KeyError as error:
            raise ToolError(f"registry row lacks {error}") from error
    keys = [(row.skill, row.step) for row in rows]
    if len(keys) != len(set(keys)):
        raise ToolError("duplicate registry row")
    return rows


def render_row(row: ToolRow) -> str:
    return skill_props.render_registry([(row.skill, row.step, row.entry)])


def add_row(text: str, row: ToolRow) -> str:
    """Registry text with `row` appended; a duplicate skill and step is rejected."""
    validate_row(row)
    if any((r.skill, r.step) == (row.skill, row.step) for r in parse_registry(text)):
        raise ToolError(f"tool already registered: {row.skill}/{row.step}")
    body = text.rstrip("\n")
    return (body + "\n\n" if body else "") + render_row(row)


def registry_path(module_root: Path) -> Path:
    return module_root / TOOLS_DIR / REGISTRY_NAME


def load_registry(module_root: Path) -> list[ToolRow]:
    path = registry_path(module_root)
    if not path.is_file():
        return []
    return parse_registry(path.read_text())


def find_tool(
    roots: Iterable[Path], skill: str, step: str
) -> tuple[Path, ToolRow] | None:
    """The module root and row registering `skill/step`, first match wins."""
    for root in roots:
        for row in load_registry(root):
            if (row.skill, row.step) == (skill, step):
                return root, row
    return None


def package_roots() -> list[Path]:
    """Package roots of installed `varde.skills` providers."""
    return [
        Path(str(files(point.value))) for point in entry_points(group="varde.skills")
    ]


def sync_target() -> Path | None:
    """The saved `[sync].skills_dir`, or None when unsaved or not a directory."""
    table = memory_dirs.load_config_document().get("sync")
    value = table.get("skills_dir") if isinstance(table, dict) else None
    if not isinstance(value, str):
        return None
    path = Path(value)
    return path if path.is_dir() else None


def sync_skill_roots(skills_dir: Path) -> list[Path]:
    """Installed skill dirs under `skills_dir` (those holding the sidecar)."""
    return sorted(
        path
        for path in skills_dir.iterdir()
        if path.is_dir() and installed_skill(skills_dir, path.name) is not None
    )


NO_SYNC_TARGET = "no sync target; run varde setup sync"


def require_sync_target() -> Path:
    target = sync_target()
    if target is None:
        raise ToolError(NO_SYNC_TARGET)
    return target


def installed_skill(skills_dir: Path, name: str) -> Path | None:
    """The synced skill dir `name` under `skills_dir`, or None when not installed."""
    path = skills_dir / name
    sidecar = path / skill_props.SIDECAR
    return path if sidecar.is_file() and not sidecar.is_symlink() else None


def installed_roots() -> list[Path]:
    """Synced skill dirs, or none when no sync target is saved."""
    target = sync_target()
    return sync_skill_roots(target) if target is not None else []


def module_roots() -> list[Path]:
    """Installed skill dirs, then package roots plus the agent dirs under them."""
    roots: list[Path] = installed_roots()
    for base in package_roots():
        roots.append(base)
        agents = base / "agents"
        if agents.is_dir():
            roots.extend(sorted(path for path in agents.iterdir() if path.is_dir()))
    return roots


def all_rows(roots: Iterable[Path]) -> list[ToolRow]:
    """Registry rows of all roots; the first row of a skill and step wins."""
    rows: dict[tuple[str, str], ToolRow] = {}
    for root in roots:
        for row in load_registry(root):
            rows.setdefault((row.skill, row.step), row)
    return list(rows.values())


def _load_run(path: Path) -> Callable[[list[str]], int]:
    spec = importlib.util.spec_from_file_location(f"step_tool_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ToolError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run


def run_counted(
    skill: str, step: str, args: Sequence[str], roots: Iterable[Path]
) -> int:
    """Run the tool and append its counter row; 2 when it is not registered."""
    found = find_tool(roots, skill, step)
    if found is None:
        print(f"error: no step tool {skill}/{step}", file=sys.stderr)
        return 2
    root, row = found
    started = time.monotonic()
    code = 1
    try:
        code = _load_run(root / TOOLS_DIR / row.entry)(list(args))
    finally:
        calls.append_tool_call(
            skill,
            step,
            status=calls.SUCCESS if code == 0 else calls.FAILURE,
            duration_s=time.monotonic() - started,
        )
    return code


def main(argv: Sequence[str]) -> int:
    target, rest = (argv[0], argv[1:]) if argv else ("", [])
    skill, _, step = target.partition("/")
    if not skill or not step:
        print("usage: tool_entry <skill>/<step> [args...]", file=sys.stderr)
        return 2
    return run_counted(skill, step, rest, module_roots())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
