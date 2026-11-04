"""Parsing and worktree checks for uv tool mutations."""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path


def deny_worktree_tool_install(command: str, cwd: str) -> str | None:
    """Return a denial reason for uv tool mutations in a linked worktree."""
    if _has_unsafe_tool_install(command, Path(cwd).expanduser()):
        return (
            "uv tool install/upgrade/uninstall is blocked when the command or "
            "install source is in a linked worktree. Install only from the main "
            "checkout after merge, or build a PEX to a temp dir."
        )
    return None


CONTROL_WORDS = {"if", "then", "else", "elif", "fi", "do", "done", "!"}
_WRAPPERS = {"env", "sudo", "command", "time", "nohup", "xargs"}
_BOOLEAN_OPTIONS = {
    "-E",
    "-H",
    "-i",
    "-k",
    "-n",
    "-p",
    "-P",
    "-q",
    "-v",
    "-x",
    "--help",
    "--ignore-environment",
    "--login",
    "--no-pager",
    "--preserve-env",
    "--quiet",
    "--verbose",
}
_WRAPPER_VALUE_OPTIONS = {
    "-a",
    "-C",
    "-D",
    "-d",
    "-E",
    "-f",
    "-g",
    "-h",
    "-I",
    "-L",
    "-n",
    "-o",
    "-P",
    "-p",
    "-R",
    "-r",
    "-s",
    "-T",
    "-t",
    "-U",
    "-u",
    "--chdir",
    "--default-signal",
    "--groups",
    "--host",
    "--prompt",
    "--unset",
}
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _has_unsafe_tool_install(command: str, cwd: Path, depth: int = 0) -> bool:
    if depth > 4:
        return False
    words = tokenize_command(command)
    if words is None:
        return False
    cwd_stack: list[Path] = []
    current_cwd = cwd
    segment: list[str] = []
    for word in words:
        if is_separator(word):
            if _unsafe_segment(segment, current_cwd, depth):
                return True
            current_cwd = _update_cd(segment, current_cwd)
            segment.clear()
            if word == "(":
                cwd_stack.append(current_cwd)
            elif word == ")" and cwd_stack:
                current_cwd = cwd_stack.pop()
            continue
        segment.append(word)
    return _unsafe_segment(segment, current_cwd, depth)


def _separate_unquoted_newlines(command: str) -> str:
    quote: str | None = None
    escaped = False
    result: list[str] = []
    for character in command:
        if escaped:
            result.append(character)
            escaped = False
            continue
        if character == "\\" and quote != "'":
            result.append(character)
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            result.append(character)
            continue
        result.append(";" if character == "\n" and quote is None else character)
    return "".join(result)


def is_separator(token: str) -> bool:
    return bool(token) and all(char in ";&|()\n{}" for char in token)


def _unsafe_segment(segment: list[str], cwd: Path, depth: int) -> bool:
    words = segment.copy()
    while words and words[0] in CONTROL_WORDS:
        words.pop(0)
    if not words or Path(words[0]).name == "echo":
        return False
    command = Path(words[0]).name
    if command in {"exec", "eval"}:
        remainder = words[1:]
        if command == "exec" and len(remainder) > 1 and remainder[0] == "-a":
            remainder = remainder[2:]
        nested_command = (
            remainder[0]
            if command == "eval" and len(remainder) == 1
            else shlex.join(remainder)
        )
        return _has_unsafe_tool_install(nested_command, cwd, depth + 1)
    executable_index = wrapped_executable_index(
        words, commands=frozenset({"uv", "bash", "sh", "zsh"})
    )
    if executable_index is None:
        return False
    executable = Path(words[executable_index]).name
    if executable in {"bash", "sh", "zsh"}:
        command_index = shell_command_index(words, executable_index + 1)
        if (
            command_index is not None
            and command_index < len(words)
            and _has_unsafe_tool_install(words[command_index], cwd, depth + 1)
        ):
            return True
    if Path(words[executable_index]).name != "uv":
        return False
    tool_index = _next_subcommand(words, executable_index + 1, "tool")
    if tool_index is None:
        return False
    verb_index = _next_subcommand(
        words, tool_index + 1, ("install", "upgrade", "uninstall")
    )
    if verb_index is None:
        return False
    return _is_worktree(cwd) or any(
        _is_worktree(_resolve_path(option_path, cwd))
        for option_path in _install_source_paths(words, executable_index)
    )


def shell_command_index(words: list[str], start: int) -> int | None:
    index = start
    while index < len(words):
        option = words[index]
        if option == "--":
            return None
        if option == "-c":
            command_index = index + 1
            while command_index < len(words) and words[command_index] in {"-x", "-v"}:
                command_index += 1
            return command_index
        if option in {"-o", "-O"}:
            index += 2
            continue
        if option.startswith("-") and not option.startswith("--") and "c" in option[1:]:
            return index + 1
        if not option.startswith("-"):
            return None
        index += 1
    return None


def tokenize_command(command: str) -> list[str] | None:
    try:
        tokens = shlex.shlex(
            _separate_unquoted_newlines(command),
            posix=True,
            punctuation_chars=";&|(){}",
        )
        tokens.whitespace_split = True
        return list(tokens)
    except ValueError:
        return None


def wrapped_executable_index(
    words: list[str], *, commands: frozenset[str]
) -> int | None:
    index = 0
    while index < len(words):
        word = words[index]
        if _ENV_ASSIGNMENT.match(word):
            index += 1
            continue
        executable = Path(word).name
        if executable in commands:
            return index
        if executable not in _WRAPPERS:
            return None
        wrapper_value_options = _WRAPPER_VALUE_OPTIONS
        if executable == "sudo":
            wrapper_value_options = _WRAPPER_VALUE_OPTIONS - {"-E"}
        elif executable == "time":
            wrapper_value_options = _WRAPPER_VALUE_OPTIONS - {"-p"}
        index += 1
        while index < len(words) and words[index].startswith("-"):
            option = words[index]
            index += 1
            if option == "--":
                break
            takes_value = option in wrapper_value_options
            if takes_value and index < len(words):
                index += 1
        if executable == "command" and index < len(words) and words[index] == "--":
            index += 1
    return None


def _next_subcommand(
    words: list[str], start: int, names: str | tuple[str, ...]
) -> int | None:
    accepted = {names} if isinstance(names, str) else set(names)
    index = start
    while index < len(words):
        word = words[index]
        if word in accepted:
            return index
        if not word.startswith("-"):
            return None
        takes_value = (
            "=" not in word
            and word not in _BOOLEAN_OPTIONS
            and (index + 1 >= len(words) or words[index + 1] not in accepted)
        )
        index += 2 if takes_value else 1
    return None


def _install_source_paths(words: list[str], uv_index: int) -> list[str]:
    paths: list[str] = []
    index = uv_index + 1
    while index < len(words):
        word = words[index]
        option, separator, value = word.partition("=")
        if option in {"--from", "--directory", "--project"}:
            if separator:
                paths.append(value)
            elif index + 1 < len(words):
                index += 1
                paths.append(words[index])
        index += 1
    return paths


def _resolve_path(value: str, cwd: Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else cwd / path).resolve()


def _update_cd(segment: list[str], cwd: Path) -> Path:
    words = segment.copy()
    while words and words[0] in CONTROL_WORDS:
        words.pop(0)
    if not words or Path(words[0]).name != "cd":
        return cwd
    target_index = 2 if len(words) > 1 and words[1] == "--" else 1
    if target_index >= len(words) or words[target_index] == "-":
        return cwd
    target = Path(words[target_index]).expanduser()
    return (target if target.is_absolute() else cwd / target).resolve()


def _is_worktree(path: Path) -> bool:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if candidate.is_file():
        candidate = candidate.parent
    try:
        result = subprocess.run(  # noqa: S603 - fixed git query uses resolved path
            [  # noqa: S607 - fixed system git command
                "git",
                "-C",
                str(candidate),
                "rev-parse",
                "--absolute-git-dir",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
    except OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired:
        return False
    directories = result.stdout.splitlines()
    return (
        len(directories) == 2
        and Path(directories[0]).resolve() != Path(directories[1]).resolve()
    )
