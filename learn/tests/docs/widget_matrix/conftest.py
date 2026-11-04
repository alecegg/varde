"""Fixtures for the widget matrix: one multi-process Chromium per session."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

from .driver import Matrix

SINGLE_PROCESS_ENV = "VARDE_WIDGET_SINGLE_PROCESS"


@pytest.fixture(scope="session")
def matrix_browser() -> Iterator[Any]:
    # The matrix opens many contexts, so it avoids --single-process (which dies
    # when a page closes); set VARDE_WIDGET_SINGLE_PROCESS=1 inside a sandbox.
    args = ["--disable-gpu"]
    if os.environ.get(SINGLE_PROCESS_ENV):
        args += ["--single-process", "--no-zygote"]
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
    except (ImportError, OSError) as exc:
        pytest.fail(f"Widget matrix needs Playwright: {exc}", pytrace=False)
    try:
        browser = playwright.chromium.launch(args=args)
    except (OSError, PlaywrightError) as exc:
        playwright.stop()
        pytest.fail(f"Widget matrix could not launch Chromium: {exc}", pytrace=False)
    try:
        yield browser
        browser.close()
    finally:
        playwright.stop()


@pytest.fixture(scope="session")
def matrix(matrix_browser: Any) -> Iterator[Matrix]:
    holder = Matrix(matrix_browser)
    yield holder
    holder.close()
