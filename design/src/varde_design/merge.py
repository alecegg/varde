"""Pure merge of static and rendered findings into one list."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .render_rules import drop_shadowed_r7
from .report import Finding

REPEATED_ACROSS_WIDTHS = ("R6",)
DEV_SERVER_NOTE = (
    "R6: dev-server build ({file}); console errors there may be dev-only, "
    "re-check against a production build"
)


@dataclass(frozen=True)
class RenderOutcome:
    """What the rendered tier produced, in plain data."""

    findings: list[Finding] = field(default_factory=list)
    widths: list[int] = field(default_factory=list)
    not_run: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ran(self) -> bool:
        return bool(self.widths)


def dedupe_widths(findings: list[Finding]) -> list[Finding]:
    """One finding per page-wide error repeated at several widths.

    The kept finding names every width in its message and carries the first.
    """
    groups: dict[tuple[str, str, str], list[Finding]] = {}
    for finding in findings:
        key = (finding.id, finding.file, finding.message)
        groups.setdefault(key, []).append(finding)
    merged: list[Finding] = []
    for key, group in groups.items():
        if key[0] not in REPEATED_ACROSS_WIDTHS or len(group) == 1:
            merged += group
            continue
        widths = sorted({f.width for f in group if f.width is not None})
        listed = ", ".join(str(w) for w in widths)
        merged.append(
            replace(
                group[0], width=widths[0], message=f"{group[0].message} (at {listed}px)"
            )
        )
    return merged


def merge_findings(static: list[Finding], rendered: list[Finding]) -> list[Finding]:
    """Static plus deduplicated rendered findings, shadowed R7 dropped."""
    return drop_shadowed_r7(static + dedupe_widths(rendered))


def dev_server_notes(metrics_list: list[dict]) -> list[str]:
    """One note per probed page whose measurements say it is a dev-server build."""
    return [
        DEV_SERVER_NOTE.format(file=metrics["target"])
        for metrics in metrics_list
        if any(entry.get("dev_server") for entry in metrics["widths"])
    ]
