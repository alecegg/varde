"""Finding factory shared by the static rule modules."""

from __future__ import annotations

from .css_scanner import Declaration, StyleRule
from .registry import RULES_BY_ID
from .report import Finding


def style_finding(
    rule_id: str,
    file: str,
    rule: StyleRule,
    decl: Declaration,
    message: str,
    severity: str | None = None,
) -> Finding:
    """A static finding on one declaration; severity defaults to the registry's."""
    return Finding(
        id=rule_id,
        severity=severity or RULES_BY_ID[rule_id].severity,
        tier="static",
        file=file,
        message=message,
        line=decl.line,
        selector=rule.selector,
        snippet=f"{decl.prop}: {decl.value}",
    )
