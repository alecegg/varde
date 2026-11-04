"""Filesystem side of check and tokens: targets, settings discovery, token sheets."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .check import is_css, is_html
from .settings import CONFIG_NAME, Settings, find_config, load_settings
from .survey import MAX_READ_BYTES, PROJECT_MARKERS
from .survey_walk import walk_project
from .tokens import MAX_SHEETS

MAX_KB = MAX_READ_BYTES // 1024


@dataclass
class Targets:
    files: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)


def read_capped(path: Path) -> tuple[str | None, str]:
    """Text of path, or (None, reason) when it is oversized or unreadable."""
    try:
        if path.stat().st_size > MAX_READ_BYTES:
            return None, f"{path}: not read, over {MAX_KB} KB"
        return path.read_text(encoding="utf-8", errors="replace"), ""
    except OSError as error:
        return None, f"{path}: unreadable ({error.strerror or error})"


def is_url(target: str) -> bool:
    return target.lower().startswith(("http://", "https://"))


def _add_file(targets: Targets, path: Path) -> None:
    text, reason = read_capped(path)
    if text is None:
        targets.skipped.append(reason)
        return
    targets.files[str(path)] = text


def _add_dir(targets: Targets, folder: Path) -> None:
    walk = walk_project(folder)
    for rel in walk.paths:
        if is_html(rel) or is_css(rel):
            _add_file(targets, folder / rel)
    if walk.truncated:
        targets.skipped.append(f"{folder}: walk stopped at its file or time cap")


def read_targets(args: list[str]) -> Targets:
    """Read every .html/.css file named by args (files, or folders walked)."""
    targets = Targets()
    for arg in args:
        path = Path(arg)
        if is_url(arg):
            targets.skipped.append(f"{arg}: URLs need the rendered tier")
        elif path.is_dir():
            _add_dir(targets, path)
        elif path.is_file() and (is_html(arg) or is_css(arg)):
            _add_file(targets, path)
        elif path.is_file():
            targets.skipped.append(f"{arg}: not an .html or .css file")
        else:
            targets.skipped.append(f"{arg}: not found")
    return targets


def project_root(args: list[str]) -> Path:
    """Nearest folder at or above the first target holding a config or marker."""
    first = Path(args[0]) if args and not is_url(args[0]) else Path(".")
    start = (first if first.is_dir() else first.parent).resolve()
    for folder in (start, *start.parents):
        if find_config(folder) or any((folder / m).exists() for m in PROJECT_MARKERS):
            return folder
    return start


def load_project_settings(config_flag: str | None, root: Path) -> tuple[Settings, str]:
    """Settings from --config, else root/varde-design.toml, else the defaults."""
    path = Path(config_flag) if config_flag else find_config(root)
    if path is None:
        return Settings(), "defaults"
    return load_settings(path), str(path) if config_flag else CONFIG_NAME


def _css_files(root: Path) -> list[Path]:
    walk = walk_project(root)
    return [root / rel for rel in walk.paths if is_css(rel)][:MAX_SHEETS]


def read_sheets(paths: list[Path]) -> tuple[list[str], list[str]]:
    sheets: list[str] = []
    skipped: list[str] = []
    for path in paths:
        text, reason = read_capped(path)
        if text is None:
            skipped.append(reason)
        else:
            sheets.append(text)
    return sheets, skipped


def token_sheets(
    settings: Settings, root: Path, tokens_flag: str | None
) -> tuple[list[str], list[str]]:
    """CSS texts defining tokens: --tokens, else token_files, else project .css."""
    if tokens_flag:
        return read_sheets([Path(tokens_flag)])
    if settings.token_files:
        return read_sheets([root / name for name in settings.token_files])
    return read_sheets(_css_files(root))
