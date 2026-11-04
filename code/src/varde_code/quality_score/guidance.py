"""How to fix a score loss: goal and per-function actions in user terms.

Pure formatting of the ``fix_targets`` that ``breakdown`` records. Numbers are
small source quantities (tokens, complexity, counts, line numbers), never
scoring units.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

MICRO = 1_000_000

GOALS = {
    "cognitive": "keep cognitive complexity at or below {t} in each function",
    "long_side": "keep each function at or below {t} tokens",
    "small_side": "avoid functions under {t} tokens unless they name a real concept",
    "params": "keep each function at or below {t} parameters",
    "names": "give every function a specific, unabbreviated name",
    "depth": "keep call chains at or below {t} levels",
    "fan_out": "keep each function at or below {t} distinct callees",
    "tree_size": "keep each call tree at or below {t} functions",
    "fragmentation": "keep at most {t} tiny single-caller helpers per file",
    "nesting": "keep control-flow nesting at or below {t} levels in each function",
    "vague_names": "bind no more than {t} vague names (data, tmp, ...) per function",
    "delegation": "keep at most {t} one-call wrapper functions per file",
}
UNITS = {
    "cognitive": "cognitive complexity",
    "long_side": "tokens",
    "small_side": "tokens",
    "params": "parameters",
    "names": "name issues",
    "depth": "call depth",
    "fan_out": "distinct callees",
    "tree_size": "call-tree functions",
    "nesting": "nesting levels",
    "vague_names": "vague names",
}
ACTIONS = {
    "cognitive": (
        "simplify `{f}` (complexity {now}, limit {t}): flatten nesting with guard "
        "clauses or extract the branch that does a separate job"
    ),
    "long_side": (
        "split `{f}` ({now} tokens{cx}) at its responsibility boundaries so each "
        "part is at most {t} tokens"
    ),
    "small_side": (
        "inline `{f}` ({now} tokens) into its caller unless it names a real concept"
    ),
    "params": (
        "cut `{f}` from {now} to at most {t} parameters: group related ones or "
        "drop unused ones"
    ),
    "names": "rename `{f}` ({issues}) to a specific, unabbreviated name",
    "depth": (
        "shorten the call chain under `{f}` (depth {now}, limit {t}): call the "
        "final helper directly or inline pass-through wrappers"
    ),
    "fan_out": (
        "reduce the distinct functions `{f}` calls ({now}, limit {t}): group "
        "related calls behind one helper"
    ),
    "tree_size": (
        "shrink the call tree under `{f}` ({now} functions, limit {t}): remove "
        "pass-through helpers"
    ),
    "fragmentation": (
        "inline `{f}` ({tokens} tokens, called only in this file) into its caller; "
        "the file has {now} such helpers, keep at most {t}"
    ),
    "nesting": (
        "flatten `{f}` (nesting {now}, limit {t}): return early with guard clauses "
        "or extract the nested branch"
    ),
    "vague_names": (
        "rename the {now} vague names bound in `{f}` (limit {t}) to say what they hold"
    ),
    "delegation": (
        "inline `{f}` (it only calls one other function, {tokens} tokens) into its "
        "callers or give it a real job; the file has {now} such wrappers, keep at "
        "most {t}"
    ),
}
FILE_ACTIONS = {
    "fragmentation": "inline tiny single-caller helpers in `{f}`",
    "file_size": "split `{f}` into cohesive modules",
    "import_fan_out": "reduce the dependency spread of `{f}`",
    "file_overhead": "consolidate tiny files such as `{f}`",
    "module_fragmentation": "inline tiny cross-file helpers used by `{f}`",
}


def category_guidance(name: str, targets: list[dict[str, Any]]) -> dict[str, Any]:
    """Optional ``goal`` and ``worst`` keys for one category; empty if no targets."""
    worst = [_worst(name, target) for target in targets]
    guidance: dict[str, Any] = {}
    goal = _goal(name, targets)
    if goal:
        guidance["goal"] = goal
    if worst:
        guidance["worst"] = worst
    return guidance


def short_name(function_id: str) -> str:
    """``module.py::Owner.run#1`` -> ``Owner.run``."""
    return function_id.rsplit("::", 1)[-1].split("#", 1)[0]


def _goal(name: str, targets: list[dict[str, Any]]) -> str:
    template = GOALS.get(name)
    if template is None or not targets:
        return ""
    limit = targets[0].get("target")
    if "{t}" in template and limit is None:
        return ""
    return template.format(t=limit)


def _worst(name: str, target: dict[str, Any]) -> dict[str, Any]:
    is_file = target.get("line") is None and name in FILE_ACTIONS
    label = target["path"] if is_file else short_name(str(target["id"]))
    item: dict[str, Any] = {
        "function": label,
        "file": target["path"],
        "loss_share": _percent(target["share"]),
        "action": _action(name, label, target),
    }
    if target.get("line") is not None:
        item["line"] = target["line"]
    if not is_file:
        item.update(now=target["now"], target=target["target"])
    return item


def _action(name: str, label: str, target: dict[str, Any]) -> str:
    if target.get("line") is None and name in FILE_ACTIONS:
        return FILE_ACTIONS[name].format(f=label)
    if target.get("within_limit"):
        return (
            f"no function is over the limit; the loss is spread across "
            f"{target['spread']} functions (largest: `{label}`, {target['now']} "
            f"{UNITS[name]}, limit {target['target']})"
        )
    complexity = target.get("complexity")
    return ACTIONS[name].format(
        tokens=target.get("tokens"),
        f=label,
        now=target["now"],
        t=target["target"],
        cx=f", complexity {complexity}" if complexity else "",
        issues=", ".join(target.get("issues") or ()) or "unclear",
    )


def _percent(share_micro: int) -> int:
    """Whole percent of the category loss, half-up, within 0-100."""
    percent = int(Fraction(share_micro, MICRO) * 100 + Fraction(1, 2))
    return max(0, min(100, percent))
