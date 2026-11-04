"""Pure, default-deny permission guard policy helpers."""

from __future__ import annotations

import os
import re
import shlex
from typing import Any

from varde_runner.config import ConfigError, Role
from varde_runner.decision_metrics import (
    _is_secret_like,
    candidates,
    classify_request_kind,
    redact_request_key,
)
from varde_runner.guard_memory_tier import classify_memory_write

_NEVER_ALLOWLIST = frozenset({"credential", "scope_change", "network", "other"})
_KNOWN_KINDS = _NEVER_ALLOWLIST | {"command_prefix", "path_scope"}
_SHELL_META = re.compile(r"[&|;\n`<>]|\$\(|\$\{")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
_WRAPPERS = frozenset(
    {"env", "time", "nohup", "command", "exec", "xargs", "sudo", "nice", "eval"}
)
_INTERPRETERS = {"bash", "sh", "zsh", "python", "python3"}
_SAFE_SINGLE = frozenset({"pytest", "ls", "cat", "rg", "grep", "head", "tail"})
_SAFE_GIT = frozenset({"status", "diff", "log", "show", "add", "commit", "branch"})
_SAFE_VARDE = frozenset({"read", "status", "list"})
_PROTECTED = re.compile(
    r"(?i)(?:^|[/\\.\s])(?:\.claude(?:\.json)?|\.mcp\.json|\.agents|\.codex|"
    r"\.git[/\\](?:config|hooks)|\.ssh|\.env[^/\\]*|\.envrc|"
    r"\.bashrc|\.bash_profile|\.zshrc|\.zprofile|\.profile|"
    r"settings(?:\.local)?\.json|managed-settings|sandbox[^/\\]*|"
    r"hooks?|skills?)(?=$|[/\\.\s:'\"]|[?#])|"
    r"(?:^|[/\\])(?:CLAUDE|AGENTS)\.md(?=$|[/\\\s:'\"])"
)


_GIT_BRANCH_FLAGS = frozenset({"-a", "--all", "-r", "--remotes", "-v", "--verbose"})
_GIT_RISKY_LONG = ("--output", "--ext-diff", "--textconv")
_SED_PRINT_RANGE = re.compile(r"\d+(?:,(?:\d+|\$))?p")
_LS_CHARS = "laA1hRtrdF"
# tool -> (exact flags, short-flag cluster characters, flags that take a value)
_TOOL_FLAGS: dict[str, tuple[frozenset[str], str, frozenset[str]]] = {
    "cat": (frozenset({"--number"}), "nbs", frozenset()),
    "ls": (frozenset({"--all", "--almost-all"}), _LS_CHARS, frozenset()),
    "head": (frozenset(), "0123456789", frozenset({"-n", "-c", "--lines", "--bytes"})),
    "tail": (frozenset(), "0123456789", frozenset({"-n", "-c", "--lines", "--bytes"})),
    "grep": (
        frozenset(
            {
                "--ignore-case",
                "--line-number",
                "--recursive",
                "--files-with-matches",
                "--count",
                "--fixed-strings",
                "--extended-regexp",
                "--word-regexp",
                "--invert-match",
                "--no-filename",
                "--with-filename",
            }
        ),
        "inrRlvwEFHhcsqoI",
        frozenset({"-m", "-A", "-B", "-C", "--max-count"}),
    ),
    "rg": (
        frozenset(
            {
                "--files",
                "--ignore-case",
                "--line-number",
                "--files-with-matches",
                "--count",
                "--fixed-strings",
                "--word-regexp",
                "--smart-case",
                "--no-heading",
                "--invert-match",
            }
        ),
        "inlvwFsScHN",
        frozenset(
            {"-g", "-t", "-m", "-A", "-B", "-C", "--glob", "--type", "--max-count"}
        ),
    ),
    "pytest": (
        frozenset(
            {
                "--lf",
                "--ff",
                "--collect-only",
                "--co",
                "--tb=short",
                "--tb=line",
                "--tb=no",
            }
        ),
        "qvxs",
        frozenset({"-k", "-m", "--maxfail"}),
    ),
    "ruff": (
        frozenset({"--no-fix", "--quiet", "--statistics", "--diff", "--no-cache"}),
        "q",
        frozenset({"--select", "--ignore", "--extend-select", "--output-format"}),
    ),
}
_PATHLESS_FIRST = frozenset({"grep", "rg"})


def _resolve(token: str, base: str) -> str | None:
    """Resolve a path token (~, $HOME, relative, ..) or None when unresolvable."""
    home = os.path.expanduser("~")
    expanded = re.sub(r"^\$HOME(?=/|$)", home, token)
    if "$" in expanded:
        return None
    expanded = os.path.expanduser(expanded)
    return os.path.realpath(os.path.join(base, expanded))


def _in_workspace(resolved: str, workspace_root: str) -> bool:
    root = os.path.realpath(workspace_root)
    return resolved == root or resolved.startswith(root + os.sep)


def _paths_in_workspace(paths: list[str], workspace_root: str) -> bool:
    base = workspace_root
    for path in paths:
        resolved = _resolve(path.split("::", 1)[0], base)
        if resolved is None or not _in_workspace(resolved, workspace_root):
            return False
    return True


def _positionals(args: list[str], spec) -> list[str] | None:
    """Return positional args, or None when any flag is not exactly allowed."""
    exact, cluster, valued = spec
    result: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg == "--" or not arg.startswith("-") or arg == "-":
            result.append(arg)
            continue
        name, equals, _ = arg.partition("=")
        if name in valued and name.startswith("--") and equals:
            continue
        if arg in valued:
            if index >= len(args):
                return None
            index += 1
            continue
        if arg in exact:
            continue
        if not arg.startswith("--") and all(char in cluster for char in arg[1:]):
            continue
        return None
    return None if "--" in result else result


def _tool_args_safe(tool: str, args: list[str], workspace_root: str) -> bool:
    positionals = _positionals(args, _TOOL_FLAGS[tool])
    if positionals is None:
        return False
    if tool in _PATHLESS_FIRST and "--files" not in args:
        if not positionals:
            return False
        positionals = positionals[1:]
    return _paths_in_workspace(positionals, workspace_root)


def _sed_safe(args: list[str], workspace_root: str) -> bool:
    if len(args) < 2 or args[0] != "-n":
        return False
    if not _SED_PRINT_RANGE.fullmatch(args[1]):
        return False
    return _paths_in_workspace(args[2:], workspace_root)


def _git_risky_flag(subcommand: str, arg: str) -> bool:
    if arg.startswith("--"):
        name = arg.split("=", 1)[0]
        if len(name) >= 4 and any(risky.startswith(name) for risky in _GIT_RISKY_LONG):
            return True
        return subcommand == "add" and len(name) >= 4 and "--force".startswith(name)
    return subcommand == "add" and arg.startswith("-") and "f" in arg[1:]


def _strings(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)
    elif isinstance(value, str):
        yield value


def _sensitive_shape(payload: dict[str, Any]) -> str | None:
    for key, value in _mapping_items(payload):
        lowered = key.lower()
        if lowered in {
            "url",
            "uri",
            "host",
            "hostname",
            "credential",
            "secret",
            "token",
            "password",
        }:
            return "network or secret-class request field"
        if _is_secret_like(key) or (isinstance(value, str) and _is_secret_like(value)):
            return "secret-like content"
    return None


def _mapping_items(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from _mapping_items(child)
    elif isinstance(value, list):
        for child in value:
            yield from _mapping_items(child)


def _request_paths(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in {"path", "file_path", "directory"}:
                if isinstance(child, str):
                    yield child
                elif isinstance(child, list):
                    yield from (item for item in child if isinstance(item, str))
            yield from _request_paths(child)
    elif isinstance(value, list):
        for child in value:
            yield from _request_paths(child)


def _protected_text(value: str) -> bool:
    expanded = re.sub(r"(?<![A-Za-z0-9_])~(?=/|$)", os.path.expanduser("~"), value)
    expanded = os.path.expanduser(expanded)
    normalized = os.path.normpath(expanded)
    return bool(_PROTECTED.search(expanded) or _PROTECTED.search(normalized))


def _command(payload: dict[str, Any]) -> str | None:
    for key, value in _mapping_items(payload):
        if key.lower() in {"command", "cmd", "shell"} and isinstance(value, str):
            return value
    return None


def _git_subcommand(
    tokens: list[str], workspace_root: str
) -> tuple[str | None, list[str]]:
    index = 1
    base = workspace_root
    while index < len(tokens):
        token = tokens[index]
        if token == "-C":  # noqa: S105 - git's directory option
            directory = (
                _resolve(tokens[index + 1], base) if index + 1 < len(tokens) else None
            )
            if directory is None or not _in_workspace(directory, workspace_root):
                return None, []
            base = directory
            index += 2
            continue
        if token in {"-c", "--config-env"} or token.startswith("--config-env="):
            return None, []
        if token.startswith("-"):
            return None, []
        return token, tokens[index + 1 :]
    return None, []


def _safe_command(command: str, workspace_root: str) -> bool:
    if _SHELL_META.search(command):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    while tokens and _ASSIGNMENT.fullmatch(tokens[0]):
        tokens.pop(0)
    if not tokens:
        return False
    executable = os.path.basename(tokens[0])
    args = tokens[1:]
    if executable in _WRAPPERS or executable in _INTERPRETERS:
        return False
    return _tool_safe(executable, args, tokens, workspace_root)


def _tool_safe(
    executable: str, args: list[str], tokens: list[str], workspace_root: str
) -> bool:
    if executable in _TOOL_FLAGS:
        return _tool_args_safe(executable, args, workspace_root)
    if executable == "sed":
        return _sed_safe(args, workspace_root)
    if executable == "ruff":
        return bool(args and args[0] == "check") and _tool_args_safe(
            "ruff", args[1:], workspace_root
        )
    if executable == "uv":
        return _uv_safe(args, workspace_root)
    if executable == "git":
        return _git_safe(tokens, workspace_root)
    if executable == "varde":
        return bool(args and args[0] in _SAFE_VARDE)
    return False


def _uv_safe(args: list[str], workspace_root: str) -> bool:
    if len(args) < 2 or args[0] != "run":
        return False
    if args[1] == "pytest":
        return _tool_args_safe("pytest", args[2:], workspace_root)
    if args[1] == "ruff":
        return args[2:3] == ["check"] and _tool_args_safe(
            "ruff", args[3:], workspace_root
        )
    return False


def _git_safe(tokens: list[str], workspace_root: str) -> bool:
    subcommand, subargs = _git_subcommand(tokens, workspace_root)
    if subcommand not in _SAFE_GIT:
        return False
    if subcommand == "branch":
        return all(arg in _GIT_BRANCH_FLAGS for arg in subargs)
    if subcommand in {"diff", "log", "show", "add"}:
        return not any(_git_risky_flag(subcommand, arg) for arg in subargs)
    return True


def _command_reason(command: str, workspace_root: str) -> str | None:
    if _SHELL_META.search(command):
        return "shell operators or redirection"
    try:
        tokens = shlex.split(command)
    except ValueError:
        return "command parse error"
    while tokens and _ASSIGNMENT.fullmatch(tokens[0]):
        tokens.pop(0)
    if not tokens:
        return "empty command"
    executable = os.path.basename(tokens[0])
    if executable in _WRAPPERS or executable in _INTERPRETERS:
        return "command wrapper or interpreter"
    if not _safe_command(command, workspace_root):
        return "command is outside the safe command set"
    if any(_protected_text(token) for token in tokens[1:]):
        return "command references protected path"
    return None


def must_escalate(
    kind: str, payload: dict[str, Any], workspace_root: str | None
) -> str | None:
    """Return a reason when policy requires escalation."""
    reasons = [
        "unknown request kind" if kind not in _KNOWN_KINDS else None,
        _sensitive_shape(payload),
    ]
    memory_tier = classify_memory_write(payload)
    reasons.append(
        memory_tier["reason"]
        if memory_tier is not None and memory_tier["outcome"] == "flag"
        else None
    )
    classified = classify_request_kind(payload)
    if kind in _NEVER_ALLOWLIST or classified in _NEVER_ALLOWLIST:
        reasons.append(f"request kind {kind} is never guard-approved")
    else:
        reasons.append(None)
    if any(_protected_text(value) for value in _strings(payload)):
        reasons.append("request references protected path")
    else:
        reasons.append(None)
    if kind == "path_scope":
        reasons.append(_path_scope_reason(payload, workspace_root))
    if command := _command(payload):
        reasons.append(
            "workspace root unavailable"
            if not workspace_root
            else _command_reason(command, workspace_root)
        )
    elif kind == "command_prefix":
        reasons.append("missing command")
    return next((reason for reason in reasons if reason), None)


def _path_scope_reason(
    payload: dict[str, Any], workspace_root: str | None
) -> str | None:
    if not workspace_root:
        return "workspace root unavailable"
    for path in _request_paths(payload):
        resolved = _resolve(path, workspace_root)
        if resolved is None or not _in_workspace(resolved, workspace_root):
            return "path is outside the session workspace"
    return None


def allowlist(
    rows: list[dict[str, Any]],
    min_approvals: int = 3,
    revoked: frozenset[str] = frozenset(),
) -> list[str]:
    """Return eligible, non-revoked keys within the safe command set."""
    return [
        key
        for key in candidates(rows, min_approvals)
        if key not in revoked
        and not key.endswith("*")
        and key.partition(":")[0] not in _NEVER_ALLOWLIST
        and _safe_key(key)
    ]


def _safe_key(key: str) -> bool:
    kind, separator, suffix = key.partition(":")
    if not separator or not suffix or suffix.endswith("*"):
        return False
    if kind == "command_prefix":
        executable = os.path.basename(suffix)
        return executable in _SAFE_SINGLE | {"ruff", "uv", "git", "varde"}
    return kind == "path_scope" and not _protected_text(suffix)


def verdict(
    kind: str,
    payload: dict[str, Any],
    workspace_root: str | None,
    allowed: list[str] | set[str] | frozenset[str],
) -> dict[str, str]:
    """Choose approve or escalate, rechecking the complete safety policy."""
    request_key = redact_request_key(kind, payload, workspace_root)
    reason = must_escalate(kind, payload, workspace_root)
    if reason:
        return {"verdict": "escalate", "reason": reason, "request_key": request_key}
    if kind in _NEVER_ALLOWLIST or not _safe_key(request_key):
        return {
            "verdict": "escalate",
            "reason": "unsafe request key",
            "request_key": request_key,
        }
    if request_key in allowed and not request_key.endswith("*"):
        return {
            "verdict": "approve",
            "reason": "allowlist match",
            "request_key": request_key,
        }
    return {
        "verdict": "escalate",
        "reason": "no allowlist match",
        "request_key": request_key,
    }


def validate_guard_role(role: Role, registry: Any) -> None:
    """Require the primary and fallbacks to use verified read-only plugins."""
    if not role.enabled:
        return
    for model in (role, *role.fallback):
        capabilities = registry.capabilities(model.harness)
        if not capabilities.guard_read_only:
            raise ConfigError(
                f"guard role harness {model.harness} is not verified read-only"
            )
