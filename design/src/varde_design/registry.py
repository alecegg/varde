"""Rule registry: one plain-data table, no rule logic."""

from __future__ import annotations

from dataclasses import dataclass

PROFILES = ("core", "opinion")
# Finding ids that are not rules: a malformed or too-short design-ignore comment.
META_FINDING_IDS = ("IGN",)


@dataclass(frozen=True)
class Rule:
    """Registry entry for one rule.

    severity is the strongest outcome (a rule with a weaker variant keeps the
    strongest here); tier is where the rule runs; gate marks rules in the usable
    gate of the later A/B.
    """

    id: str
    severity: str
    tier: str
    profile: str
    summary: str
    gate: bool = False


def _rule(
    rule_id: str,
    severity: str,
    tier: str,
    summary: str,
    *,
    profile: str = "core",
    gate: bool = False,
) -> Rule:
    return Rule(rule_id, severity, tier, profile, summary, gate)


RULES: tuple[Rule, ...] = (
    _rule(
        "S1", "warn", "static", "Tracked-caps label above a heading", profile="opinion"
    ),
    _rule("S2", "warn", "static", "Gradient text via background-clip"),
    _rule("S3", "warn", "static", "Accent side border on a card", profile="opinion"),
    _rule("S4", "warn", "both", "Text below the minimum size"),
    _rule(
        "S5",
        "warn",
        "static",
        "Missing lang, title or viewport; no h1 or skipped heading (opinion)",
    ),
    _rule("S6", "fail", "static", "Image without alt text or with a broken source"),
    _rule(
        "S7",
        "warn",
        "static",
        "Colour literal outside the token set",
        profile="opinion",
    ),
    _rule("S8", "warn", "static", "Placeholder copy", profile="opinion"),
    _rule("S9", "warn", "static", "Spacing off the scale", profile="opinion"),
    _rule("S10", "warn", "static", "Motion defect", profile="opinion"),
    _rule("R1", "fail", "rendered", "Text contrast below threshold", gate=True),
    _rule("R2", "fail", "rendered", "Horizontal overflow", gate=True),
    _rule("R3", "warn", "rendered", "Interactive target too small", gate=True),
    _rule("R4", "warn", "rendered", "Headline over two lines", profile="opinion"),
    _rule("R5", "warn", "rendered", "Declared font is not the rendered font"),
    _rule("R6", "fail", "rendered", "Console or page error", gate=True),
    _rule(
        "R7", "warn", "both", "Missing or low-contrast focus ring", profile="opinion"
    ),
    _rule("R8", "warn", "rendered", "Line length outside the reading range"),
)

RULES_BY_ID: dict[str, Rule] = {rule.id: rule for rule in RULES}


def rule_ids() -> tuple[str, ...]:
    return tuple(rule.id for rule in RULES)


def active_rules(profile: str) -> tuple[Rule, ...]:
    """Rules that run under profile: core runs core rules; opinion adds the rest."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile: {profile}")
    if profile == "opinion":
        return RULES
    return tuple(rule for rule in RULES if rule.profile == "core")
