"""Plain-text rendering of the user view, a few lines per category."""

from __future__ import annotations

from typing import Any


def score_label(calibration: str) -> str:
    """The calibration label; an unvalidated score is also marked report-only."""
    return calibration.replace("not validated", "not validated / report-only")


def render_text(view: dict[str, Any]) -> str:
    """Render the user view; categories ordered by points lost, then name."""
    if view.get("notice"):
        return str(view["notice"]) + "\n"
    lines = [f"Score: {view['score']} / 100 ({score_label(view['calibration'])})"]
    refactor = view.get("refactor")
    if refactor and refactor.get("message"):
        lines.append("Relative to your code: " + refactor["message"])
    if view.get("tests_passed") is not None:
        lines.append(f"Tests passed: {view['tests_passed']}")
    lines.extend(_fix_lines(view.get("fixes") or ()))
    ordered = sorted(view["categories"], key=lambda c: (-c["points_lost"], c["name"]))
    for category in ordered:
        lines.extend(_category_lines(category))
    lines.extend(
        "Advisory (score unchanged): " + view[key]["action"]
        for key in ("monolith", "delegation", "fragmentation")
        if view.get(key)
    )
    return "\n".join(lines) + "\n"


def _category_lines(category: dict[str, Any]) -> list[str]:
    head = f"{category['name']}: -{category['points_lost']} points. "
    lines = [head + category.get("goal", category["hint"])]
    for item in category.get("worst", ()):
        place = f"{item['file']}:{item['line']}" if "line" in item else item["file"]
        lines.append(f"  - {item['action']} [{place}, {item['loss_share']}% of loss]")
    return lines


def _fix_lines(fixes: Any) -> list[str]:
    if not fixes:
        return []
    lines = ["What to change, in order:"]
    for fix in fixes:
        place = f"{fix['file']}:{fix['line']}" if fix.get("line") else fix["file"]
        effect = (
            f"predicted score {fix['predicted_score']}"
            if fix["predicted_score"] is not None
            else "score claim: none"
        )
        lines.append(
            f"  {fix['rank']}. {fix['change']} [{place}, {fix['contribution_points']} "
            f"points of loss, {fix['distance_to_line']} below the line, {effect}]"
        )
    return lines
