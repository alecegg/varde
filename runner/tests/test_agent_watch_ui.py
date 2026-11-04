from __future__ import annotations

import http.server
import json
import socketserver
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import sync_playwright


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


@pytest.fixture
def watch_page(catalog_origin):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            args=["--single-process", "--no-zygote", "--disable-gpu"]
        )
        page = browser.new_page()
        page.add_init_script("""
          window.watchSources = [];
          window.EventSource = class {
            constructor(url) {
              this.url = url;
              this.listeners = {};
              this.closed = false;
              window.watchSources.push(this);
            }
            addEventListener(name, callback) {
              (this.listeners[name] ||= []).push(callback);
            }
            close() { this.closed = true; }
            dispatch(name, data) {
              for (const callback of this.listeners[name] || []) callback({data});
            }
          };
        """)
        try:
            yield page
        finally:
            browser.close()


def open_watch(page, catalog_origin):
    page.goto(f"{catalog_origin}/_catalog")
    page.locator("details.other > summary").click()
    button = page.get_by_role("button", name="Watch Catalog agent")
    assert button.locator("span").first.inner_text() == "Watch"
    assert button.get_attribute("aria-label") == "Watch Catalog agent"
    button.click()
    return page.evaluate(
        "window.watchSources.findIndex(source => source.url.includes('/watch?'))"
    )


def dispatch(page, index, event, data):
    page.evaluate(
        """({index, event, data}) =>
          window.watchSources[index].dispatch(event, data)""",
        {"index": index, "event": event, "data": data},
    )


def sources(page):
    return page.evaluate(
        "window.watchSources.filter(source => "
        "source.url.includes('/watch?')).map(source => ({"
        "url: source.url, closed: source.closed}))"
    )


def test_watch_uses_observer_stream_and_reconnects_after_last_event(
    watch_page, catalog_origin
):
    page = watch_page
    first_index = open_watch(page, catalog_origin)
    first = page.evaluate("index => window.watchSources[index].url", first_index)
    parsed = urlparse(first)
    query = parse_qs(parsed.query)
    assert parsed.path == "/api/agents/catalog-agent-1/watch"
    assert query["role"] == ["observer"]
    assert query["client"][0]
    assert len(sources(page)) == 1

    dispatch(
        page,
        first_index,
        "snapshot",
        '{"last_seq":7,"events":[],"open_intents":[],"pending_waits":[]}',
    )
    assert page.get_by_text("Snapshot · sequence 7").is_visible()
    assert page.locator(".watch [role='status']").count() == 0
    dispatch(
        page,
        first_index,
        "event",
        '{"seq":8,"kind":"message","payload":{"text":"hello"}}',
    )
    assert page.get_by_text("Sequence 8").is_visible()
    assert page.get_by_text('"text": "hello"').is_visible()

    dispatch(page, first_index, "error", None)
    page.wait_for_function(
        "window.watchSources.filter(source => "
        "source.url.includes('/watch?')).length === 2"
    )
    watch_sources = sources(page)
    second_query = parse_qs(urlparse(watch_sources[1]["url"]).query)
    assert second_query["client"] == query["client"]
    assert second_query["after"] == ["8"]
    assert watch_sources[0]["closed"]


def test_outer_collapse_closes_watch(watch_page, catalog_origin):
    page = watch_page
    index = open_watch(page, catalog_origin)
    page.locator("details.other > summary").click()
    page.wait_for_function("index => window.watchSources[index].closed", arg=index)
    assert page.evaluate("index => window.watchSources[index].closed", index)
    assert page.locator("[aria-label='Agent watch']").count() == 0


def test_error_frame_stops_watch(watch_page, catalog_origin):
    page = watch_page
    index = open_watch(page, catalog_origin)
    dispatch(page, index, "error", '{"error":"agent ended"}')
    assert page.evaluate("index => window.watchSources[index].closed", index)
    assert page.locator(".watch [role='status']").count() == 0
    page.wait_for_timeout(1200)
    assert len(sources(page)) == 1


def test_invalid_frame_stops_watch(watch_page, catalog_origin):
    page = watch_page
    index = open_watch(page, catalog_origin)
    dispatch(page, index, "snapshot", '{"last_seq":"invalid","events":[]}')
    assert page.evaluate("index => window.watchSources[index].closed", index)
    assert page.locator(".watch [role='status']").count() == 0


def test_snapshot_and_live_events_are_bounded_to_shared_window(
    watch_page, catalog_origin
):
    page = watch_page
    index = open_watch(page, catalog_origin)
    snapshot_events = [
        {"seq": seq, "kind": "message", "payload": {"value": seq}}
        for seq in range(1, 61)
    ]
    dispatch(
        page,
        index,
        "snapshot",
        json.dumps({"last_seq": 60, "events": snapshot_events}),
    )
    assert page.get_by_text("Sequence 11").is_visible()
    assert page.get_by_text("Sequence 10").count() == 0
    assert page.locator(".event").count() == 50

    for seq in range(61, 121):
        dispatch(
            page,
            index,
            "event",
            json.dumps({"seq": seq, "kind": "message", "payload": {"value": seq}}),
        )
    assert page.locator(".event").count() == 50
    assert page.get_by_text("Sequence 71").is_visible()
    assert page.get_by_text("Sequence 70").count() == 0

    dispatch(page, index, "error", None)
    page.wait_for_function(
        "window.watchSources.filter(source => "
        "source.url.includes('/watch?')).length === 2"
    )
    second_index = page.evaluate(
        "window.watchSources.findLastIndex(source => source.url.includes('/watch?'))"
    )
    dispatch(
        page,
        second_index,
        "snapshot",
        json.dumps(
            {
                "last_seq": 200,
                "events": [
                    {"seq": seq, "kind": "message", "payload": {"value": seq}}
                    for seq in range(151, 201)
                ],
            }
        ),
    )
    assert page.locator(".event").count() == 50
    assert page.get_by_text("Sequence 151").is_visible()
    assert page.get_by_text("Sequence 120").count() == 0


def test_collapse_cancels_retry_without_reopening(watch_page, catalog_origin):
    page = watch_page
    index = open_watch(page, catalog_origin)
    dispatch(page, index, "error", None)
    assert page.locator(".watch [role='status']").count() == 0
    page.get_by_role("button", name="Watch Catalog agent").click()
    assert page.evaluate("index => window.watchSources[index].closed", index)
    page.wait_for_timeout(1200)
    assert len(sources(page)) == 1


def test_retries_back_off_and_stop_after_consecutive_failures(
    watch_page, catalog_origin
):
    page = watch_page
    first_index = open_watch(page, catalog_origin)
    page.evaluate("""() => {
      const nativeSetTimeout = window.setTimeout.bind(window);
      window.watchDelays = [];
      window.setTimeout = (callback, delay, ...args) => {
        window.watchDelays.push(delay);
        return nativeSetTimeout(callback, 0, ...args);
      };
    }""")

    dispatch(page, first_index, "error", None)
    page.wait_for_function(
        "window.watchSources.filter(source => "
        "source.url.includes('/watch?')).length === 2"
    )
    current_index = page.evaluate(
        "window.watchSources.findLastIndex(source => source.url.includes('/watch?'))"
    )
    dispatch(
        page,
        current_index,
        "snapshot",
        '{"last_seq":0,"events":[]}',
    )

    expected_delays = [1000, 2000, 4000, 8000]
    for retry_number in range(4):
        dispatch(page, current_index, "error", None)
        expected_sources = retry_number + 3
        page.wait_for_function(
            "count => window.watchSources.filter(source => "
            "source.url.includes('/watch?')).length === count",
            arg=expected_sources,
        )
        current_index = page.evaluate(
            "window.watchSources.findLastIndex(source => "
            "source.url.includes('/watch?'))"
        )

    dispatch(page, current_index, "error", None)
    assert page.locator(".watch [role='status']").count() == 0
    assert [1000, *expected_delays] == page.evaluate("window.watchDelays")
    assert len(sources(page)) == 6
