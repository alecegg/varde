"""Detect git worktree prune commands before they can run in an agent session."""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path

from .tool_install_guard import (
    CONTROL_WORDS,
    is_separator,
    shell_command_index,
    tokenize_command,
    wrapped_executable_index,
)

_COMMANDS = frozenset({"git", "bash", "sh", "zsh"})
_GIT_VALUE_OPTIONS = {
    "--config-env",
    "--git-dir",
    "--namespace",
    "--work-tree",
}
_SUBMODULE_DEPTH = 4
_DENIAL = "git worktree prune is blocked for callers other than main."


def deny_worktree_prune(
    command: str, resolve_caller_address: Callable[[], str | None]
) -> str | None:
    """Return a denial reason, resolving the caller only for prune commands."""
    if not contains_worktree_prune(command):
        return None
    return None if resolve_caller_address() == "main" else _DENIAL


def is_primary_checkout(cwd: str | None) -> bool:
    """True when cwd is inside the primary checkout of a git repository.

    A submodule is judged by its superproject, so a submodule of a linked
    worktree is not primary. Bare repositories keep git-dir == common-dir.
    False on any error, a missing or non-string cwd, or inherited git
    location variables that could redirect the query.
    """
    if not isinstance(cwd, str) or not cwd:
        return False
    if "GIT_DIR" in os.environ or "GIT_COMMON_DIR" in os.environ:
        return False
    for _ in range(_SUBMODULE_DEPTH):
        output = _git_lines(
            cwd,
            # --path-format=absolute requires git >= 2.31.
            ["rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"],
        )
        if output is None or len(output) != 2:
            return False
        if os.path.realpath(output[0]) != os.path.realpath(output[1]):
            return False
        superproject = _git_lines(
            cwd, ["rev-parse", "--show-superproject-working-tree"]
        )
        if superproject is None:
            return False
        if not superproject:
            return True
        cwd = superproject[0]
    return False


def _git_lines(cwd: str, args: list[str]) -> list[str] | None:
    try:
        result = subprocess.run(  # noqa: S603 - fixed git query
            ["git", "-C", cwd, *args],  # noqa: S607 - fixed system git command
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
    except OSError, ValueError, subprocess.SubprocessError:
        return None
    return result.stdout.splitlines()


def resolve_unmailboxed_caller(payload: dict, cwd: str | None) -> str | None:
    """Name main without the mailbox: no agent_id, cwd in the primary checkout."""
    if "agent_id" in payload:
        return None
    return "main" if is_primary_checkout(cwd) else None


def contains_worktree_prune(command: str, depth: int = 0) -> bool:
    if depth > 4:
        return False
    if any(
        contains_worktree_prune(nested, depth + 1)
        for nested in _command_substitutions(command)
    ):
        return True
    words = tokenize_command(command)
    if words is None:
        return False
    segment: list[str] = []
    for word in words:
        if is_separator(word):
            if _segment_prunes(segment, depth):
                return True
            segment.clear()
            continue
        segment.append(word)
    return _segment_prunes(segment, depth)


def _segment_prunes(segment: list[str], depth: int) -> bool:
    words = segment.copy()
    while words and words[0] in CONTROL_WORDS:
        words.pop(0)
    if not words:
        return False
    if Path(words[0]).name in {"exec", "eval"}:
        remainder = words[1:]
        if (
            Path(words[0]).name == "exec"
            and len(remainder) > 1
            and remainder[0] == "-a"
        ):
            remainder = remainder[2:]
        nested = (
            remainder[0]
            if Path(words[0]).name == "eval" and len(remainder) == 1
            else shlex.join(remainder)
        )
        return contains_worktree_prune(nested, depth + 1)

    executable_index = wrapped_executable_index(words, commands=_COMMANDS)
    if executable_index is None:
        return False
    executable = Path(words[executable_index]).name
    if executable in {"bash", "sh", "zsh"}:
        command_index = shell_command_index(words, executable_index + 1)
        return (
            command_index is not None
            and command_index < len(words)
            and contains_worktree_prune(words[command_index], depth + 1)
        )
    return executable == "git" and _is_worktree_prune(words, executable_index)


def _command_substitutions(command: str) -> list[str]:
    nested: list[str] = []
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(command):
        character = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            index += 1
            continue
        if quote != "'" and character == "`":
            end = command.find("`", index + 1)
            if end != -1:
                nested.append(command[index + 1 : end])
                index = end + 1
                continue
        if quote != "'" and command.startswith("$(", index):
            end = _command_substitution_end(command, index + 2)
            if end is not None:
                nested.append(command[index + 2 : end])
                index = end + 1
                continue
        index += 1
    return nested


def _command_substitution_end(command: str, start: int) -> int | None:
    depth = 1
    quote: str | None = None
    escaped = False
    for index in range(start, len(command)):
        character = command[index]
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote != "'":
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            continue
        if quote is not None:
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _is_worktree_prune(words: list[str], git_index: int) -> bool:
    index = git_index + 1
    while index < len(words):
        option = words[index]
        if option in {"-h", "--help"}:
            return False
        if option in {"-C", "-c", *_GIT_VALUE_OPTIONS}:
            index += 2
            continue
        option_name, has_assignment, _ = option.partition("=")
        if option_name in {"-C", "-c", *_GIT_VALUE_OPTIONS} and has_assignment:
            index += 1
            continue
        if option.startswith("-"):
            # --exec-path accepts an optional attached value, never a
            # separately consumed argument. Other unknown global flags are
            # valueless unless they appear in _GIT_VALUE_OPTIONS.
            index += 1
            continue
        break
    return (
        index + 1 < len(words)
        and words[index] == "worktree"
        and words[index + 1] == "prune"
    )
