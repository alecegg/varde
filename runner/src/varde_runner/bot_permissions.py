"""Closed argv allowlist for the manager bot's shell requests (pure).

Only three exact command forms are allowed; every other request is denied.
The tokenizer rejects shell syntax first, so quoting tricks never reach it.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass

# Anything that lets a command string do more than name one program with arguments.
_SHELL_SYNTAX = re.compile(r"[;&|<>`$(){}\\!*?~#\[\]\n\r\t\"']")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_ACT_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_PLAN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_PLAN_COMMANDS = frozenset({"status", "readiness", "merged"})
_SHELL_TOOLS = frozenset({"bash", "shell"})


@dataclass(frozen=True, slots=True)
class Decision:
    allow: bool
    reason: str
    action: str = ""


def _deny(reason: str) -> Decision:
    return Decision(False, reason)


def decide(command: str | list[str]) -> Decision:
    """Allow three forms only: ``varde-runner bot act <name>``,
    ``varde plan status|readiness|merged <plan>``, ``varde msg read --as manager``."""
    if isinstance(command, str):
        if _SHELL_SYNTAX.search(command):
            return _deny("shell syntax is not allowed")
        try:
            argv = shlex.split(command)
        except ValueError:
            return _deny("command cannot be tokenized")
    else:
        argv = list(command)
    if not argv:
        return _deny("empty command")
    if _ASSIGNMENT.match(argv[0]):
        return _deny("environment prefixes are not allowed")
    return _decide_argv(argv)


def _decide_argv(argv: list[str]) -> Decision:
    match argv:
        case ["varde-runner", "bot", "act", name] if _ACT_NAME.fullmatch(name):
            return Decision(True, "bot act", "bot_act")
        case ["varde", "plan", sub, plan] if (
            sub in _PLAN_COMMANDS and _PLAN_ID.fullmatch(plan)
        ):
            return Decision(True, f"plan {sub}", f"plan_{sub}")
        case ["varde", "msg", "read", "--as", "manager"]:
            return Decision(True, "msg read", "msg_read")
    return _deny("command is not on the allowlist")


def decide_request(payload: Mapping[str, object]) -> Decision:
    """Decide a permission request. Only shell requests can be allowed; a file tool
    request that reaches the host, a network tool or anything else is denied."""
    tool = payload.get("tool")
    if not isinstance(tool, str) or tool.lower() not in _SHELL_TOOLS:
        return _deny(f"tool {tool!r} is not allowed for the bot")
    tool_input = payload.get("input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return _deny("request has no command")
    return decide(command)
