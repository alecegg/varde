"""Render probe: one browser launch, every width, plain-data measurements.

The only module that touches Playwright, imported lazily so the package works
without the optional `render` extra. All decisions live in `judge`.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .probe_focus import walk_focus
from .probe_script import MAX_ELEMENTS, PROBE_SCRIPT

METRICS_SCHEMA = 1
NAV_TIMEOUT_MS = 15_000
SETTLE_TIMEOUT_MS = 1_500
VIEWPORT_HEIGHT = 900
# Single-process Chromium avoids the Mach-port registration that fails in a
# sandbox; closing a page then kills the browser, so one page is reused.
BROWSER_ARGS = ["--single-process", "--no-zygote", "--disable-gpu"]
INSTALL_HINT = (
    "install the render tier with `pip install 'varde-design[render]'` "
    "(in a repository checkout: `uv sync --extra render`), then run "
    "`playwright install chromium`"
)
DEV_SERVER_SCRIPT = """() =>
  !!document.querySelector(
    'script[src*="@vite/client"],script[src*="webpack-dev-server"],'
    + 'script[src*="react-refresh"],script[src*="__nextjs"]')"""
_URL_SCHEMES = ("http://", "https://", "file://")


@dataclass(frozen=True)
class NotRun:
    reason: str

    def message(self) -> str:
        return f"render: not run ({self.reason}); {INSTALL_HINT}"


def target_url(target: str) -> str | NotRun:
    """A URL for a URL or an existing file path."""
    if target.startswith(_URL_SCHEMES):
        return target
    path = Path(target)
    if not path.is_file():
        return NotRun(f"target not found: {target}")
    return path.resolve().as_uri()


def _probe_widths(page: Any, url: str, widths: tuple[int, ...]) -> list[dict[str, Any]]:
    errors: list[dict[str, str]] = []
    page.on(
        "console",
        lambda m: (
            m.type == "error"
            and errors.append(
                {"kind": "console", "text": m.text, "url": m.location.get("url", "")}
            )
        ),
    )
    page.on(
        "pageerror",
        lambda e: errors.append({"kind": "pageerror", "text": str(e), "url": ""}),
    )
    results: list[dict[str, Any]] = []
    for width in widths:
        errors.clear()
        page.set_viewport_size({"width": width, "height": VIEWPORT_HEIGHT})
        page.goto(url, wait_until="load", timeout=NAV_TIMEOUT_MS)
        # Open connections never go idle; measure anyway after the settle wait.
        with contextlib.suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
        measured = page.evaluate(PROBE_SCRIPT, MAX_ELEMENTS)
        # The Tab walk is width-independent enough to run once, at the widest width.
        focus = walk_focus(page) if width == max(widths) else None
        dev_server = bool(page.evaluate(DEV_SERVER_SCRIPT))
        results.append(
            {
                "width": width,
                **measured,
                "errors": list(errors),
                "focus": focus,
                "dev_server": dev_server,
            }
        )
    return results


def probe(target: str, widths: tuple[int, ...]) -> dict[str, Any] | NotRun:
    """Measure the target at each width in one launch, or explain why not."""
    url = target_url(target)
    if isinstance(url, NotRun):
        return url
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return NotRun("playwright is not installed")
    try:
        playwright = sync_playwright().start()
    except (OSError, PlaywrightError) as exc:
        return NotRun(f"playwright did not start: {exc}")
    try:
        browser = playwright.chromium.launch(args=BROWSER_ARGS)
    except (OSError, PlaywrightError) as exc:
        playwright.stop()
        return NotRun(f"chromium did not launch: {str(exc).splitlines()[0]}")
    try:
        page = browser.new_page()
        measured = _probe_widths(page, url, widths)
    except (OSError, PlaywrightError) as exc:
        return NotRun(f"page could not be measured: {str(exc).splitlines()[0]}")
    finally:
        browser.close()
        playwright.stop()
    return {"schema": METRICS_SCHEMA, "target": target, "widths": measured}
