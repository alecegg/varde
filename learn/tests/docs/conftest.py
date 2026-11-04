"""Chromium launch fixtures for the page browser tests.

Copied from the runner's browser fixtures (not imported): the browser fails the
test, never skips it, so a missing browser or sandbox read grant is visible.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

BROWSER_ARGS = ["--single-process", "--no-zygote", "--disable-gpu"]


def _launch_browser(launch: Callable[..., Any]) -> Any:
    return launch(args=BROWSER_ARGS)


def _browser_launch_error(error: Exception) -> str:
    browser_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not browser_root:
        cache = (
            "Library/Caches/ms-playwright"
            if platform.system() == "Darwin"
            else ".cache/ms-playwright"
        )
        browser_root = str(Path.home() / cache)
    if browser_root == "0":
        browser_root = "the Playwright package-local browser directory"
    return (
        "Page browser tests require Playwright Chromium. From the repo root, "
        "run `uv run playwright install chromium`. If Chromium is already "
        "installed but unreadable in a sandbox, grant filesystem allowRead for "
        f"the Playwright browser cache at {browser_root}. "
        f"Browser launch failed: {error}"
    )


@pytest.fixture(scope="module")
def browser_session() -> Iterator[Any]:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
    except (ImportError, OSError) as exc:
        pytest.fail(
            "Page browser tests require Playwright Python dependencies. From "
            f"the repo root, run `uv sync --group dev`. Error: {exc}",
            pytrace=False,
        )
    try:
        browser = _launch_browser(playwright.chromium.launch)
    except (OSError, PlaywrightError) as exc:
        playwright.stop()
        pytest.fail(_browser_launch_error(exc), pytrace=False)
    try:
        yield browser
        browser.close()
    finally:
        playwright.stop()
