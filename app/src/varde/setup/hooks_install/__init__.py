"""Install hooks for Claude, Codex, OpenCode, and Pi."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from ..old_store import SetupError, check_old_store
from ..opencode_version import is_below_floor, parse_version
from .common import home_dir, write_atomic
from .json_hooks import EVENTS, apply, stable_varde_path
from .json_hooks import HARNESSES as JSON_HARNESSES

FEATURES = ("change", "toz", "learn", "code", "knowledge")
HARNESSES = (*JSON_HARNESSES, "opencode", "pi")
MARKER = "// varde-managed: fnv64="
PLACEHOLDER = '"{{VARDE_BIN}}"'
PROBE_TIMEOUT = 2
OPENCODE_UNSUPPORTED = (
    "no per-user-prompt hook adds context; the context hook runs on every model call"
)


def _parser(action: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"varde setup hooks {action}")
    parser.add_argument("--harness", action="append", choices=HARNESSES)
    parser.add_argument(
        "--skip-event",
        action="append",
        choices=tuple(event.key for event in EVENTS),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--features", action="append")
    parser.add_argument("--force", action="store_true")
    return parser


def run(args: Sequence[str]) -> int:
    """Run the install/remove action; the first argument names the action."""
    argv = list(args)
    action = "remove" if argv and argv[0] == "remove" else "install"
    parsed = _parser(action).parse_args(argv[1:])
    harnesses = list(dict.fromkeys(parsed.harness or HARNESSES))
    features = (
        tuple(
            feature for group in (parsed.features or []) for feature in group.split(",")
        )
        or None
    )
    invalid = sorted(set(features or ()) - set(FEATURES))
    if invalid:
        _parser(action).error(f"invalid feature: {invalid[0]}")
    try:
        check_old_store()
        for harness in harnesses:
            if harness in JSON_HARNESSES:
                lines = next(
                    apply(
                        action == "install",
                        [harness],
                        parsed.force,
                        parsed.skip_event or (),
                        features,
                    )
                )[1]
            else:
                lines = plugin_file(
                    harness, action == "install", parsed.force, features
                )
            if action == "install" and harness == "opencode":
                lines.append(
                    f"opencode: user-prompt-submit unsupported ({OPENCODE_UNSUPPORTED})"
                )
            for line in lines:
                print(line)
            if action == "install" and harness == "codex":
                print(
                    "codex: needs `hooks = true` in ~/.codex/config.toml; open Codex, "
                    "run /hooks, review and trust the Varde hooks, then run "
                    "`varde setup doctor` to verify"
                )
    except (OSError, ValueError, RuntimeError, SetupError) as error:
        print(f"varde setup hooks {action}: {error}", file=sys.stderr)
        return 1
    return 0


__all__ = ["run"]


def config_home(home: Path) -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")


def pi_agent_dir(home: Path) -> Path:
    return Path(os.environ.get("PI_CODING_AGENT_DIR") or home / ".pi/agent")


def plugin_path(harness: str, home: Path | None = None) -> Path:
    home = home if home is not None else home_dir()
    if harness == "opencode":
        return config_home(home) / "opencode/plugin/varde.ts"
    return pi_agent_dir(home) / "extensions/varde.ts"


def opencode_version() -> tuple[int, int, int] | None:
    try:
        result = subprocess.run(
            ["opencode", "--version"],  # noqa: S607 - version probe uses fixed executable
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    return parse_version(result.stdout)


def _template_for_version(
    harness: str, install: bool, version: tuple[int, int, int] | None
) -> str:
    name = "pi.ts" if harness == "pi" else "opencode.ts"
    if harness == "opencode" and install and version is not None and version[0] < 2:
        name = "opencode-v1.ts"
    return (Path(__file__).parent.parent / "assets/hooks" / name).read_text(
        encoding="utf-8"
    )


def plugin_file(
    harness: str, install: bool, force: bool, features: tuple[str, ...] | None
) -> list[str]:
    version = opencode_version() if harness == "opencode" and install else None
    template = _template_for_version(harness, install, version) if install else ""
    warning = (
        [
            (
                f"opencode: warning: {'.'.join(map(str, version))} is below the "
                "supported 2.x baseline 2.0.18; installing best effort"
            )
        ]
        if version is not None and is_below_floor(version)
        else []
    )
    path = plugin_path(harness)
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = None
    except OSError as error:
        raise OSError(f"reading {path}: {error}") from error
    if existing is None:
        if not install:
            return [f"{harness}: {path} not found, nothing to remove"]
        write_atomic(
            path,
            render_plugin(
                template,
                stable_varde_path(home_dir()),
                features,
            ),
        )
        return [f"{harness}: installed {path}", *warning]
    if not is_unedited(existing) and not force:
        action = "install" if install else "remove"
        return [
            *warning,
            (
                f"{harness}: blocked, {path} was edited or is not a Varde plugin; "
                f"kept. Fix: varde setup hooks {action} --harness {harness} --force"
            ),
        ]
    if not install:
        path.unlink()
        return [f"{harness}: removed {path}"]
    desired = render_plugin(template, stable_varde_path(home_dir()), features)
    if desired == existing:
        return [f"{harness}: {path} is up to date", *warning]
    write_atomic(path, desired)
    return [f"{harness}: installed {path}", *warning]


def render_plugin(template: str, exe: str, features: tuple[str, ...] | None) -> str:
    body = filter_plugin_features(template, features).replace(
        PLACEHOLDER, json.dumps(exe)
    )
    return f"{MARKER}{fnv64(body):016x}\n{body}"


def filter_plugin_features(template: str, features: tuple[str, ...] | None) -> str:
    stack: list[bool] = []
    output: list[str] = []
    for line in template.splitlines():
        marker = line.strip().removeprefix("// VARDE_FEATURE:")
        if marker != line.strip():
            if marker.endswith(":start"):
                name = marker.removesuffix(":start")
                parent = stack[-1] if stack else True
                stack.append(parent and feature_enabled(name, features))
                continue
            if marker.endswith(":end"):
                if stack:
                    stack.pop()
                continue
        if not stack or stack[-1]:
            output.append(line)
    body = "\n".join(output)
    return body + ("\n" if template.endswith("\n") else "")


def feature_enabled(name: str, features: tuple[str, ...] | None) -> bool:
    if features is None:
        return True
    session = "code" in features or "toz" in features
    return {
        "session-start": session,
        "toz": "toz" in features,
        "post-tool-use": any(
            item in features for item in ("toz", "knowledge", "change")
        ),
        "inbox": "change" in features,
        "agent-start": session or "change" in features,
    }.get(name, False)


def fnv64(text: str) -> int:
    value = 0xCBF29CE484222325
    for byte in text.encode():
        value = ((value ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return value


def is_unedited(text: str) -> bool:
    first, separator, body = text.partition("\n")
    if not separator or not first.startswith(MARKER):
        return False
    try:
        return int(first[len(MARKER) :], 16) == fnv64(body)
    except ValueError:
        return False
