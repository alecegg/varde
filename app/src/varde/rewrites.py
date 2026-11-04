"""Argument rewrites for the few routes with router-owned syntax."""

import json


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def rewrite_scan_setup(args: list[str]) -> list[str] | None:
    """Add operation and optional user scope to valid scan setup JSON."""
    json_value: str | None = None
    user_scope = False
    remaining: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json":
            if json_value is not None or index + 1 >= len(args):
                return None
            json_value = args[index + 1]
            index += 2
            continue
        if arg == "--user":
            if user_scope:
                return None
            user_scope = True
            index += 1
            continue
        remaining.append(arg)
        index += 1
    if json_value is None:
        return None
    try:
        payload = json.loads(json_value, parse_constant=_reject_json_constant)
    except json.JSONDecodeError, TypeError, ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    payload["operation"] = "setup"
    if user_scope:
        payload["scope"] = "user"
    return [
        "--json",
        json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False),
        *remaining,
    ]


def rewrite_seed_rule_id(args: list[str]) -> list[str] | None:
    """Move --rule-id into the code module's JSON input."""
    rule_id: str | None = None
    json_value: str | None = None
    remaining: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--rule-id":
            if rule_id is not None or index + 1 >= len(args):
                return None
            rule_id = args[index + 1]
            index += 2
            continue
        if arg == "--json":
            if json_value is not None or index + 1 >= len(args):
                return None
            json_value = args[index + 1]
            index += 2
            continue
        remaining.append(arg)
        index += 1
    if rule_id is None or json_value is None:
        return None
    try:
        payload = json.loads(json_value, parse_constant=_reject_json_constant)
    except json.JSONDecodeError, TypeError, ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    payload["ruleId"] = rule_id
    return [
        "--json",
        json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False),
        *remaining,
    ]


def rewrite_rules_diff(args: list[str]) -> list[str] | None:
    """Map the diff positional ID to the rules-list JSON operation."""
    if args and args[0] in ("--help", "-h"):
        return args
    rule_id = args[0] if args else ""
    payload = {"repoRoot": ".", "operation": "diff", "ruleId": rule_id}
    return [
        "--json",
        json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False),
        *args[1:],
    ]
