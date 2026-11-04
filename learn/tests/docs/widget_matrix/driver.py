"""Browser side of the matrix: contexts, served pages, tab walks, shots."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from varde_learn.docs.pages.serve import PageServer

from . import audit, checks
from .cells import FIXTURES, WALK_MODES, Cell, families_in, scope_for
from .rendered import ROOTS_JS, NotRendered, not_rendered

TAB_LIMIT = 150
VIEWPORT_HEIGHT = 800
ZOOM_FACTOR = 2
SHOTS_ENV = "VARDE_WIDGET_SHOTS"


def shots_dir() -> Path:
    kept = os.environ.get(SHOTS_ENV)
    path = Path(kept) if kept else Path(tempfile.mkdtemp(prefix="widget-shots-"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def context_options(cell: Cell) -> dict[str, Any]:
    options: dict[str, Any] = {
        "viewport": {"width": cell.width, "height": VIEWPORT_HEIGHT},
        "color_scheme": cell.scheme,
    }
    extra: dict[str, dict[str, Any]] = {
        "reduced-motion": {"reduced_motion": "reduce"},
        "coarse": {"has_touch": True, "is_mobile": True},
        "forced-colors": {"forced_colors": "active"},
        "nojs": {"java_script_enabled": False},
    }
    return options | extra.get(cell.mode, {})


def apply_mode(context: Any, page: Any, cell: Cell) -> None:
    """Emulation that is not a context option (zoom, print) before navigation."""
    if cell.mode == "zoom200":
        cdp = context.new_cdp_session(page)
        cdp.send(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": cell.width,
                "height": VIEWPORT_HEIGHT,
                "deviceScaleFactor": ZOOM_FACTOR,
                "mobile": False,
            },
        )
    if cell.mode == "print":
        page.emulate_media(media="print")


def tab_walk(page: Any, scope: dict[str, Any]) -> list[dict[str, Any]]:
    """Focus the first control in `scope`, then Tab until focus leaves it."""
    page.keyboard.press("Shift")  # keyboard modality, so :focus-visible applies
    if not page.evaluate(audit.FIRST_FOCUS_JS, scope):
        return []
    stops: list[dict[str, Any]] = []
    for _ in range(TAB_LIMIT):
        stop = page.evaluate(audit.FOCUS_JS, scope)
        if stop is None:
            break
        stops.append(stop)
        page.keyboard.press("Tab")
    return stops


def audit_family(page: Any, cell: Cell, family: str) -> list[str]:
    scope = scope_for(family)
    snapshot = page.evaluate(audit.COLLECT_JS, scope)
    stops = tab_walk(page, scope) if cell.mode in WALK_MODES else []
    return checks.run_checks(
        snapshot, stops, scheme=cell.scheme, mode=cell.mode, family=family
    )


class Matrix:
    """Serves the fixtures once and audits each page load for all its families."""

    def __init__(self, browser: Any) -> None:
        self.browser = browser
        self.root = Path(tempfile.mkdtemp(prefix="widget-matrix-"))
        self.shots = shots_dir()
        self.servers: dict[str, tuple[PageServer, threading.Thread]] = {}
        self.failures: dict[tuple[str, int, str, str], NotRendered] = {}
        self.results: dict[tuple[str, int, str, str], dict[str, list[str]]] = {}
        shutil.copytree(FIXTURES, self.root, dirs_exist_ok=True)

    def url(self, fixture: str) -> str:
        if fixture not in self.servers:
            server = PageServer(self.root / fixture, 0, allow_edit=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.servers[fixture] = (server, thread)
        return f"http://127.0.0.1:{self.servers[fixture][0].port}/"

    def text(self, fixture: str) -> str:
        return (self.root / fixture).read_text(encoding="utf-8")

    def shot_path(self, cell: Cell) -> Path:
        stem = cell.fixture.removesuffix(".md")
        return self.shots / f"{stem}-{cell.mode}-{cell.scheme}-w{cell.width}.png"

    def problems(self, cell: Cell) -> list[str]:
        if cell.page_key in self.failures:
            raise self.failures[cell.page_key]
        if cell.page_key not in self.results:
            try:
                self.results[cell.page_key] = self._load(cell)
            except NotRendered as error:
                self.failures[cell.page_key] = error
                raise
        return self.results[cell.page_key][cell.family]

    def _load(self, cell: Cell) -> dict[str, list[str]]:
        context = self.browser.new_context(**context_options(cell))
        try:
            page = context.new_page()
            page.set_default_timeout(15_000)
            apply_mode(context, page, cell)
            page.goto(self.url(cell.fixture))
            if cell.mode == "rtl":
                page.evaluate("document.documentElement.dir = 'rtl'")
            page.screenshot(path=str(self.shot_path(cell)), full_page=True)
            missing = not_rendered(self.text(cell.fixture), page.evaluate(ROOTS_JS))
            if missing:
                raise NotRendered(
                    f"{cell.fixture} is not rendered: " + "; ".join(missing)
                )
            return {f: audit_family(page, cell, f) for f in families_in(cell.fixture)}
        finally:
            context.close()

    def close(self) -> None:
        for server, thread in self.servers.values():
            server.shutdown()
            server.server_close()
            thread.join(5)
        shutil.rmtree(self.root, ignore_errors=True)
