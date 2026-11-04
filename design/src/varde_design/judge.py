"""Pure judgement of recorded render measurements into findings."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .registry import RULES_BY_ID, active_rules
from .render_rules import check_contrast, check_errors, check_focus, check_targets
from .report import Finding
from .settings import Settings
from .text_rules import check_fonts, check_headlines, check_line_length

Check = Callable[[dict[str, Any], str, int, Settings], list[Finding]]
OVERFLOW_TOLERANCE_PX = 1


def width_metrics(metrics: dict[str, Any], width: int) -> dict[str, Any]:
    """The measurements taken at one width."""
    for entry in metrics["widths"]:
        if entry["width"] == width:
            return entry
    raise ValueError(f"no measurements at width {width}")


def check_overflow(
    at_width: dict[str, Any], target: str, width: int, settings: Settings
) -> list[Finding]:
    """R2: the document scrolls horizontally."""
    del settings
    doc = at_width["doc"]
    extra = doc["scroll_width"] - doc["client_width"]
    if extra <= OVERFLOW_TOLERANCE_PX:
        return []
    return [
        Finding(
            id="R2",
            severity=RULES_BY_ID["R2"].severity,
            tier="rendered",
            file=target,
            width=width,
            snippet=(
                f"scrollWidth {doc['scroll_width']} > clientWidth {doc['client_width']}"
            ),
            message=f"Page overflows horizontally by {extra}px at {width}px.",
        )
    ]


# Rule checks run in this order; judge() drops findings of rules outside the profile.
RENDER_CHECKS: tuple[Check, ...] = (
    check_contrast,
    check_overflow,
    check_targets,
    check_errors,
    check_headlines,
    check_fonts,
    check_focus,
    check_line_length,
)


def judge(metrics: dict[str, Any], width: int, settings: Settings) -> list[Finding]:
    """Findings for one width of a probe result; deterministic and I/O-free."""
    widest = width == max(entry["width"] for entry in metrics["widths"])
    at_width = {**width_metrics(metrics, width), "widest": widest}
    target = metrics["target"]
    active = {rule.id for rule in active_rules(settings.profile)}
    found = [
        finding
        for check in RENDER_CHECKS
        for finding in check(at_width, target, width, settings)
        if finding.id in active
    ]
    return sorted(found, key=lambda f: (f.id, f.selector or "", f.snippet))


def judge_all(metrics: dict[str, Any], settings: Settings) -> list[Finding]:
    """Findings for every measured width."""
    return [
        finding
        for entry in metrics["widths"]
        for finding in judge(metrics, entry["width"], settings)
    ]
