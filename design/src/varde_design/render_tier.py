"""Rendered tier of `check`: probe each .html target, judge, collect an outcome.

The only I/O here is the probe call; judging and merging are pure.
"""

from __future__ import annotations

from .check import is_html
from .judge import judge_all
from .merge import RenderOutcome, dev_server_notes
from .probe import NotRun, probe
from .settings import Settings

NO_HTML = "render: no .html target to render"


def render_outcome(
    files: list[str], settings: Settings, widths: tuple[int, ...]
) -> RenderOutcome:
    """Probe every .html file at widths; a failed probe becomes a not_run entry."""
    targets = [file for file in files if is_html(file)]
    if not targets:
        return RenderOutcome(not_run=[NO_HTML])
    measured: list[dict] = []
    not_run: list[str] = []
    for target in targets:
        result = probe(target, widths)
        if isinstance(result, NotRun):
            not_run.append(result.message())
        else:
            measured.append(result)
    findings = [f for metrics in measured for f in judge_all(metrics, settings)]
    return RenderOutcome(
        findings=findings,
        widths=list(widths) if measured else [],
        not_run=list(dict.fromkeys(not_run)),
        notes=dev_server_notes(measured),
    )
