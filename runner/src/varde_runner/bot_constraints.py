"""Pure constraints on what the bot's allowed routes may do.

Each check returns None when the call is fine, or a short refusal reason. State
the checks need (workspaces, bound slots, ownership) comes in through
``ConstraintContext`` callables, so the module has no I/O.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_runner.bot_taint import is_bot_rooted
from varde_runner.bot_tokens import BOT_ACTOR, BotIdentity

DEFAULT_LAUNCH_ROLES = ("orchestrator", "planner", "explorer")
LAUNCH_FIELDS = frozenset(
    {"role", "workspace", "prompt", "address", "requested_identity"}
)
STUB_FIELDS = frozenset({"text", "idempotency_key", "project", "workspace_id"})
COMMENT_FIELDS = frozenset({"target", "text"})
QUEUE_FIELDS = frozenset({"plan", "direction"})
TEXT_FIELDS = frozenset({"text"})
MAILBOX_FIELDS = frozenset({"asked", "why", "options"})
PLAN_EDIT_FIELDS = frozenset({"body"})
AGENT_ACTIONS = frozenset({"prompt", "interrupt", "resume", "stop", "archive"})
_SLOT = re.compile(r"orchestrator-[0-9]{1,4}")


@dataclass(frozen=True, slots=True)
class BotConfig:
    launch_roles: tuple[str, ...] = DEFAULT_LAUNCH_ROLES


@dataclass(frozen=True, slots=True)
class ConstraintContext:
    workspace_listed: Callable[[str], bool]
    slot_bound: Callable[[str], bool]
    plan_bound: Callable[[str], bool]
    launched_by: Callable[[str], str | None]
    plan_exists: Callable[[str], bool]
    plan_status: Callable[[str], str | None] = lambda _plan: None


def load_bot_config(path: Path) -> BotConfig:
    """Read ``[bot].launch_roles`` from runner.toml; defaults when absent."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError:
        return BotConfig()
    roles = data.get("bot", {}).get("launch_roles")
    valid = isinstance(roles, list) and roles and all(isinstance(r, str) for r in roles)
    return BotConfig(tuple(roles)) if valid else BotConfig()


def _unknown_fields(body: Mapping[str, Any], allowed: frozenset[str]) -> str | None:
    extra = sorted(set(body) - allowed)
    return f"fields not allowed: {', '.join(extra)}" if extra else None


def check_launch(
    body: Mapping[str, Any], config: BotConfig, ctx: ConstraintContext
) -> str | None:
    if reason := _unknown_fields(body, LAUNCH_FIELDS):
        return reason
    if body.get("role") not in config.launch_roles:
        return "role is not in bot.launch_roles"
    requested_identity = body.get("requested_identity")
    if requested_identity is not None and (
        not isinstance(requested_identity, str)
        or not requested_identity.strip()
        or len(requested_identity) > 280
    ):
        return "requested_identity must be non-empty text up to 280 characters"
    workspace = body.get("workspace")
    if not isinstance(workspace, str) or not ctx.workspace_listed(workspace):
        return "workspace is not a listed workspace"
    address = body.get("address")
    if address is None:
        return None
    if not isinstance(address, dict):
        return "address must be an object"
    return _address_reason(address, ctx)


def _address_reason(address: Mapping[str, Any], ctx: ConstraintContext) -> str | None:
    slot, plan = address.get("slot"), address.get("plan")
    if not isinstance(slot, str) or not _SLOT.fullmatch(slot):
        return "slot must match orchestrator-N"
    if ctx.slot_bound(slot):
        return "slot is bound to a live agent"
    if plan is not None and (not isinstance(plan, str) or ctx.plan_bound(plan)):
        return "plan is bound to a live agent"
    return None


def check_agent_action(
    action: str,
    agent_id: str,
    identity: BotIdentity | None,
    ctx: ConstraintContext,
) -> str | None:
    if action not in AGENT_ACTIONS:
        return "action is not allowed"
    owner = ctx.launched_by(agent_id)
    if (
        identity is None
        or not is_bot_rooted(identity.actor)
        or not is_bot_rooted(owner)
    ):
        return "agent was not launched by the bot"
    if identity.actor == BOT_ACTOR:
        return None
    if identity.actor != f"{BOT_ACTOR}/{identity.session_id}":
        return "agent was not launched by the bot"
    current = agent_id
    seen: set[str] = set()
    while current not in seen:
        if current == identity.session_id:
            return None
        seen.add(current)
        launcher = ctx.launched_by(current)
        prefix = f"{BOT_ACTOR}/"
        if not isinstance(launcher, str) or not launcher.startswith(prefix):
            break
        current = launcher.removeprefix(prefix)
    return "agent was not launched by the bot"
    return None


def check_stub(body: Mapping[str, Any]) -> str | None:
    return _unknown_fields(body, STUB_FIELDS)


def check_queue_move(body: Mapping[str, Any], ctx: ConstraintContext) -> str | None:
    if reason := _unknown_fields(body, QUEUE_FIELDS):
        return reason
    plan = body.get("plan")
    return None if isinstance(plan, str) and ctx.plan_exists(plan) else "plan not found"


def check_plan_comment(
    plan_id: str, body: Mapping[str, Any], ctx: ConstraintContext
) -> str | None:
    if reason := _unknown_fields(body, COMMENT_FIELDS):
        return reason
    return None if ctx.plan_exists(plan_id) else "plan not found"


def check_plan_edit(
    plan_id: str, body: Mapping[str, Any], ctx: ConstraintContext
) -> str | None:
    if reason := _unknown_fields(body, PLAN_EDIT_FIELDS):
        return reason
    content = body.get("body")
    if not isinstance(content, str) or len(content) > 100_000:
        return "body must be text no longer than 100000 characters"
    if not ctx.plan_exists(plan_id):
        return "plan not found"
    return None if ctx.plan_status(plan_id) == "backlog" else "plan is not backlog"


def _check_text_action(body: Mapping[str, Any]) -> str | None:
    if reason := _unknown_fields(body, TEXT_FIELDS):
        return reason
    text = body.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 20_000:
        return "text must be non-empty and at most 20000 characters"
    return None


def _check_mailbox(body: Mapping[str, Any]) -> str | None:
    if reason := _unknown_fields(body, MAILBOX_FIELDS):
        return reason
    asked, why, options = body.get("asked"), body.get("why", ""), body.get("options")
    if not isinstance(asked, str) or not asked.strip() or len(asked) > 2_000:
        return "asked must be non-empty and at most 2000 characters"
    if not isinstance(why, str) or len(why) > 4_000:
        return "why must be text at most 4000 characters"
    if (
        not isinstance(options, list)
        or not options
        or len(options) > 8
        or any(
            not isinstance(item, str) or not item.strip() or len(item) > 200
            for item in options
        )
    ):
        return (
            "options must contain one to eight non-empty strings "
            "of at most 200 characters"
        )
    return None


def check(
    constraint: str,
    params: Mapping[str, Any],
    body: Mapping[str, Any],
    config: BotConfig,
    ctx: ConstraintContext,
    identity: BotIdentity | None = None,
) -> str | None:
    """Dispatch by the constraint name in the route policy. Unknown names refuse."""
    if constraint in {"bot_say", "bot_notes", "bot_mailbox", "plan_edit"}:
        return _check_additional(constraint, params, body, ctx)
    match constraint:
        case "launch":
            return check_launch(body, config, ctx)
        case "agent_action":
            return check_agent_action(
                str(params.get("action", "")),
                str(params.get("id", "")),
                identity,
                ctx,
            )
        case "stub":
            return check_stub(body)
        case "queue_move":
            return check_queue_move(body, ctx)
        case "plan_comment":
            return check_plan_comment(str(params.get("plan_id", "")), body, ctx)
    return "unknown constraint"


def _check_additional(
    constraint: str,
    params: Mapping[str, Any],
    body: Mapping[str, Any],
    ctx: ConstraintContext,
) -> str | None:
    if constraint in {"bot_say", "bot_notes"}:
        return _check_text_action(body)
    if constraint == "bot_mailbox":
        return _check_mailbox(body)
    if constraint == "plan_edit":
        return check_plan_edit(str(params.get("plan_id", "")), body, ctx)
    return "unknown constraint"
