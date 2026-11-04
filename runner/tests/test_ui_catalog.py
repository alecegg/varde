from __future__ import annotations

import http.server
import socketserver
import threading
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from test_web_browser import assert_page_text_contrast, contrast_ratio

FONT_SIZE_SCRIPT = "el => getComputedStyle(el).fontSize.replace('px','')"


@pytest.fixture(scope="module")
def catalog_origin(runner_ui_built):
    root = Path(__file__).parents[1] / "src" / "varde_runner" / "web" / "static" / "ui"

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def translate_path(self, path):
            if path.rstrip("/") == "/_catalog":
                path = "/_catalog.html"
            return super().translate_path(path)

        def log_message(self, format, *args):
            pass

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
        # Chromium opens one connection per module in the catalog bundle at
        # once; the default five-slot listen backlog resets the surplus, so the
        # page never hydrates.
        request_queue_size = 128

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def assert_shared_patterns(page, width):
    markdown = page.locator(".markdown").first
    assert markdown.locator("h3").inner_text() == "Markdown heading"
    assert markdown.locator("li").count() == 2
    assert markdown.locator("pre code").inner_text() == "block code"
    assert markdown.locator("b").count() == 0
    assert "# " not in markdown.inner_text()
    assert page.locator("section.section.attention").count() == 1
    evidence = page.locator(".evidence")
    assert evidence.locator(".diff").inner_text().startswith(" runner/ui")
    assert evidence.locator(".entry").first.locator(".diff").count() == 1
    assert evidence.locator(".thumb").bounding_box()["height"] >= 44
    assert evidence.locator(".markdown strong").inner_text() == "ready"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width == 390:
        mobile_nav = page.get_by_role("button", name="Open menu")
        assert mobile_nav.is_visible()
        assert mobile_nav.bounding_box()["height"] >= 44


def test_catalog_components_mobile_desktop_and_themes(catalog_origin):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            args=["--single-process", "--no-zygote", "--disable-gpu"]
        )
        page = browser.new_page()
        try:
            for theme in ("light", "dark"):
                for width in (390, 1440):
                    page.set_viewport_size({"width": width, "height": 900})
                    page.goto(f"{catalog_origin}/_catalog")
                    page.evaluate(
                        "theme => document.documentElement.dataset.theme = theme", theme
                    )
                    expect(
                        page.get_by_role("heading", name="Component catalog", level=1)
                    ).to_be_visible()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= innerWidth"
                    )
                    assert page.locator("button.ui-button").count() >= 6
                    assert page.locator(".icon-button").count() >= 4
                    assert page.locator("[role=tab][aria-controls]").count() == 2
                    selectors = (
                        "button.ui-button, .icon-button, input, select, textarea, "
                        "[role=tab], [role=menuitem]"
                    )
                    for control in page.locator(selectors).all():
                        if control.is_visible():
                            height_script = (
                                "el => (el.matches('input[type=checkbox]') ? "
                                "el.parentElement : el).getBoundingClientRect().height"
                            )
                            height = control.evaluate(height_script)
                            assert_script = (
                                "el => [el.tagName, el.getAttribute('role'), "
                                "el.className, el.textContent.trim(), "
                                "el.getBoundingClientRect().height, "
                                "getComputedStyle(el).height, el.style.height, "
                                "el.scrollHeight]"
                            )
                            assert height == 44, control.evaluate(assert_script)
                    assert (
                        page.locator(".ui-row-body").first.evaluate(
                            "el => el.parentElement.getBoundingClientRect().height"
                        )
                        == 52
                    )
                    assert_shared_patterns(page, width)
                    allowed_fonts = {
                        "12px",
                        "13px",
                        "14px",
                        "15px",
                        "16px",
                        "17px",
                        "18px",
                        "19px",
                        "20px",
                    }
                    font_sizes = page.locator("body *:visible").evaluate_all(
                        "els => els.map(el => getComputedStyle(el).fontSize).filter("
                        "(size, i, all) => all.indexOf(size) === i)"
                    )
                    assert set(font_sizes) <= allowed_fonts, font_sizes
                    for selector in ("input", "select", "textarea"):
                        if width == 390:
                            for item in page.locator(selector).all():
                                assert float(item.evaluate(FONT_SIZE_SCRIPT)) >= 16
                    assert_page_text_contrast(page, "_catalog")
                    for item in page.locator(
                        "[role=tab][data-state=active], button.active"
                    ).all():
                        pair = item.evaluate(
                            "el => [getComputedStyle(el).color, "
                            "getComputedStyle(el).backgroundColor]"
                        )
                        if pair[1] != "rgba(0, 0, 0, 0)":
                            assert contrast_ratio(*pair) >= 4.5, pair
                    page.get_by_role("button", name="First expandable row").click()
                    page.get_by_role("button", name="Second expandable row").click()
                    assert page.locator("#catalog-detail-1").is_hidden()
                    assert page.locator("#catalog-detail-2").is_visible()
            # Focus before shrinking, then simulate the visual viewport keyboard inset.
            page.set_viewport_size({"width": 390, "height": 900})
            field = page.locator("#catalog-reply")
            field.focus()
            page.set_viewport_size({"width": 390, "height": 420})
            page.evaluate("""() => {
              Object.defineProperty(window.visualViewport, 'height', {
                configurable: true, value: 200
              });
              window.visualViewport.dispatchEvent(new Event('resize'));
            }""")
            inset_script = (
                "el => parseFloat(getComputedStyle(el).getPropertyValue("
                "'--keyboard-inset')) > 0"
            )
            assert page.locator("form.reply").evaluate(inset_script)
            field_box = field.bounding_box()
            send_box = page.get_by_role("button", name="Send").bounding_box()
            for box in (field_box, send_box):
                assert box is not None
                assert box["y"] >= 0
                assert box["y"] + box["height"] <= 200
            cleanup_script = (
                "el => { document.querySelectorAll('form.reply, .pinned-bar')"
                ".forEach(node => { node.style.removeProperty('--keyboard-inset'); "
                "node.style.removeProperty('padding-bottom'); }); "
                "window.scrollTo(0, 0); }"
            )
            page.locator("form.reply").evaluate(cleanup_script)
            no_helper_bottom = page.get_by_role("button", name="Send").bounding_box()
            assert no_helper_bottom is not None
            assert no_helper_bottom["y"] + no_helper_bottom["height"] > 200
        finally:
            browser.close()
