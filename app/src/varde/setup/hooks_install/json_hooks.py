"""Claude and Codex hook configuration management."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde import json_order
from varde.json_order import RemoveOptions

from .common import home_dir, shell_quote, shell_words, write_atomic

HARNESSES = ("claude", "codex")
FEATURES = ("change", "toz", "learn", "code", "knowledge")


@dataclass(frozen=True)
class Event:
    key: str
    arg: str
    matcher: str | None
    timeout: int


EVENTS = (
    Event("SessionStart", "session-start", None, 20),
    Event("PreToolUse", "pre-tool-use", "Bash", 20),
    Event("PostToolUse", "post-tool-use", "*", 30),
    Event("UserPromptSubmit", "user-prompt-submit", None, 20),
    Event("Stop", "stop", None, 20),
    Event("SubagentStart", "subagent-start", None, 20),
)


@dataclass(frozen=True)
class Found:
    command: str
    unified: bool


def entry_json(event: Event, command: str) -> str:
    group: dict[str, Any] = {}
    if event.matcher is not None:
        group["matcher"] = event.matcher
    group["hooks"] = [{"type": "command", "command": command, "timeout": event.timeout}]
    return json.dumps({"hooks": {event.key: [group]}}, separators=(",", ": "))


def hook_command(exe: str, event: Event, harness: str) -> str:
    return f"{shell_quote(exe)} hook {event.arg} --harness {harness}"


def stable_varde_path(home: Path) -> str:
    link = home / ".local/bin/varde"
    return str(link if link.exists() else Path(sys.argv[0]).resolve(strict=False))


def disabled_events(features: tuple[str, ...] | None) -> tuple[str, ...]:
    if features is None:
        return ()
    enabled = {
        "PreToolUse": "change" in features,
        "SessionStart": "code" in features or "toz" in features,
        "PostToolUse": any(item in features for item in ("toz", "knowledge", "change")),
        "UserPromptSubmit": "change" in features,
        "Stop": "change" in features,
        "SubagentStart": "code" in features or "toz" in features,
    }
    return tuple(event for event, is_enabled in enabled.items() if not is_enabled)


def apply(
    install: bool,
    harnesses: list[str],
    force: bool,
    skip: tuple[str, ...],
    features: tuple[str, ...] | None,
):
    home = home_dir()
    exe = stable_varde_path(home)
    for harness in harnesses:
        path = home / (
            ".claude/settings.json" if harness == "claude" else ".codex/hooks.json"
        )
        yield (
            harness,
            json_hooks(
                path,
                harness,
                exe,
                install,
                force,
                skip,
                disabled_events(features) if install else (),
            ),
        )


def json_hooks(
    path: Path,
    harness: str,
    exe: str,
    install: bool,
    force: bool,
    skip: tuple[str, ...],
    disabled: tuple[str, ...],
) -> list[str]:
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if not install:
            return [f"{harness}: {path} not found, nothing to remove"]
        original = "{}"
    except OSError as error:
        raise OSError(f"reading {path}: {error}") from error
    try:
        doc = json.loads(original)
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(doc, dict) or (
        "hooks" in doc and not isinstance(doc["hooks"], dict)
    ):
        raise ValueError(f"{path} is not a hook config object")

    text = original
    lines: list[str] = []
    for event in EVENTS:
        if event.key in skip:
            lines.append(f"{harness}: skipped {event.key} in {path}")
            continue
        found = find_entries(doc, event, harness, exe)
        if event.key in disabled:
            managed = {entry.command for entry in found if entry.unified}
            if managed:

                def owns_managed(command: str, managed=managed) -> bool:
                    return command in managed

                text, _ = json_order.remove_matching_commands_with_options(
                    text, event.key, owns_managed, RemoveOptions(prune_empty_hooks=True)
                )
                lines.append(f"{harness}: removed {event.key} in {path}")
            continue
        edited = next((entry for entry in found if not entry.unified), None)
        if edited is not None and not force:
            lines.append(
                f"{harness}: blocked, {path} has an edited Varde {event.key} "
                f"entry ({edited.command}); kept. Fix: varde setup hooks "
                f"{'install' if install else 'remove'} --harness {harness} --force"
            )
            continue
        command = hook_command(exe, event, harness)
        current = len(found) == 1 and found[0].unified and found[0].command == command

        def owned(value: str, event=event) -> bool:
            return varde_words(value, event) is not None

        if install and current or not install and not found:
            continue
        if install:
            document = entry_json(event, command)
            result = json_order.replace_owned_entries_from_json(
                text, event.key, owned, document, event.key
            )
        else:
            result = json_order.remove_matching_commands_with_options(
                text, event.key, owned, RemoveOptions(prune_empty_hooks=True)
            )
        text = result[0]
        lines.append(
            f"{harness}: {'installed' if install else 'removed'} {event.key} in {path}"
        )
    if text != original:
        write_atomic(path, text)
    elif not lines:
        lines.append(f"{harness}: {path} is up to date")
    return lines


def find_entries(
    doc: dict[str, Any], event: Event, harness: str, exe: str
) -> list[Found]:
    hooks = doc.get("hooks", {})
    groups = hooks.get(event.key, []) if isinstance(hooks, dict) else []
    found: list[Found] = []
    for group in groups if isinstance(groups, list) else []:
        nested = group.get("hooks", []) if isinstance(group, dict) else []
        direct = [group] if isinstance(group, dict) and "command" in group else []
        group_shape = is_unified_group(group, event)
        for hook in [*(nested if isinstance(nested, list) else []), *direct]:
            command = hook.get("command") if isinstance(hook, dict) else None
            if not isinstance(command, str):
                continue
            words = varde_words(command, event)
            if words is None:
                continue
            unified = (
                group_shape
                and hook.get("type") == "command"
                and hook.get("timeout") == event.timeout
                and len(hook) == 3
                and is_unified_command(words, event, harness, exe)
            )
            found.append(Found(command, unified))
    return found


def is_unified_group(group: Any, event: Event) -> bool:
    if not isinstance(group, dict):
        return False
    keys = {"hooks"} | ({"matcher"} if event.matcher is not None else set())
    return (
        set(group) == keys
        and group.get("matcher") == event.matcher
        and isinstance(group.get("hooks"), list)
        and len(group["hooks"]) == 1
    )


def varde_words(command: str, event: Event) -> list[str] | None:
    words = shell_words(command)
    for index in range(max(0, len(words) - 2)):
        name = Path(words[index]).name
        if name in ("varde", "varde-workflow") and words[index + 1 : index + 3] == [
            "hook",
            event.arg,
        ]:
            return words
    return None


def is_unified_command(words: list[str], event: Event, harness: str, exe: str) -> bool:
    return (
        bool(words)
        and (words[0] == exe or Path(words[0]).name == "varde")
        and words[1:] == ["hook", event.arg, "--harness", harness]
    )
