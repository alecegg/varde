from __future__ import annotations

import json
import socket
import threading
import time

import pytest
import uvicorn
from stop_server import stop_server
from test_web import setup_app

pytestmark = pytest.mark.slow


def mock_events(page, snapshot):
    payload = {
        "topics": ["orchestrators", "mailbox", "work_items", "queue"],
        "needs_you_count": snapshot.get("needs_you_count", 0),
    }
    body = f"event: update\ndata: {json.dumps(payload)}\n\n"
    page.route(
        "**/events",
        lambda route: route.fulfill(content_type="text/event-stream", body=body),
    )


def reproject_messages(app):
    projector = app.state.projector
    with projector.db_lock:
        projector.db.execute("DELETE FROM inbox_projection")
        projector.db.commit()
    projector.project()


def contrast_ratio(foreground, background):
    def channel(value):
        value = value / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    def luminance(color):
        red, green, blue = map(
            int, color.removeprefix("rgb(").removesuffix(")").split(",")
        )
        return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)

    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def assert_theme_surface_contrast(page, theme):
    surfaces = page.locator("body").evaluate("""body => {
        const root = getComputedStyle(document.documentElement);
        return ['--surface-0','--surface-1','--surface-2',
          '--surface-inset','--surface-input']
          .map(token => [token, root.getPropertyValue(token).trim()]);
    }""")
    surface_values = dict(surfaces)
    for first, second in (
        ("--surface-0", "--surface-1"),
        ("--surface-1", "--surface-2"),
        ("--surface-1", "--surface-inset"),
        ("--surface-1", "--surface-input"),
    ):
        colors = page.locator("body").evaluate(
            """(body, names) => {
              const style = getComputedStyle(document.documentElement);
              const probe = document.createElement('span');
              document.body.append(probe);
              return names.map(name => {
                probe.style.color = style.getPropertyValue(name).trim();
                return getComputedStyle(probe).color;
              });
            }""",
            [first, second],
        )
        assert contrast_ratio(*colors) >= 1.03, (
            f"{theme} adjacent surfaces {first}/{second}: {surface_values}"
        )
    for foreground, background, minimum in (
        ("--text", "--surface-0", 4.5),
        ("--text", "--surface-1", 4.5),
        ("--text", "--surface-2", 4.5),
        ("--text", "--surface-inset", 4.5),
        ("--text", "--surface-input", 4.5),
        ("--code", "--surface-0", 4.5),
        ("--border-control", "--surface-input", 3),
        ("--focus", "--surface-1", 3),
    ):
        colors = page.locator("body").evaluate(
            """(body, names) => {
            const style = getComputedStyle(document.documentElement);
            const probe = document.createElement('span');
            document.body.append(probe);
            return names.map(name => {
              probe.style.color = style.getPropertyValue(name).trim();
              return getComputedStyle(probe).color;
            });
        }""",
            [foreground, background],
        )
        if foreground == "--border-control" and theme != "dark":
            continue
        assert contrast_ratio(*colors) >= minimum, (
            f"{theme} {foreground} on {background}: {colors}"
        )


def assert_page_text_contrast(page, path):
    colors = page.locator("body").evaluate(r"""body => {
        const visible = el => {
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          return rect.width > 0 && rect.height > 0 &&
            style.visibility !== 'hidden' && style.display !== 'none';
        };
        return [...body.querySelectorAll('*')]
          .filter(el => visible(el) && el.innerText?.trim()).map(el => {
          let node = el;
          let background = getComputedStyle(node).backgroundColor;
          let backgroundImage = getComputedStyle(node).backgroundImage;
          while ((background === 'rgba(0, 0, 0, 0)' ||
                 background === 'transparent') && node.parentElement) {
            node = node.parentElement;
            const style = getComputedStyle(node);
            background = style.backgroundColor;
            backgroundImage = style.backgroundImage;
            if (backgroundImage !== 'none') break;
          }
          return {
            selector: el.className?.baseVal ?? el.className ?? el.tagName,
            text: el.innerText.trim().slice(0, 40),
            pair: [getComputedStyle(el).color, background],
            gradient: backgroundImage === 'none' ? [] :
              [...backgroundImage.matchAll(/rgba?\([^)]+\)/g)].map(match => match[0]),
          };
        });
    }""")
    assert colors, f"{path} has no visible text elements"
    for item in colors:
        if any(
            token in str(item["selector"]) for token in ("circle", "avatar", "brand")
        ):
            continue  # Avatar initials sit over the role hue background.
        backgrounds = item["gradient"] or [item["pair"][1]]
        assert all(
            contrast_ratio(item["pair"][0], background) >= 4.5
            for background in backgrounds
        ), (
            f"{path} {item['selector']} {item['text']!r} contrast {item['pair']} {backgrounds}"
        )

    assert page.locator(".chat-shell:visible").count() == 1, f"{path} has no chat shell"
    controls_selector = (
        ".mailbox-tools input:visible, .role-fields select:visible, "
        ".fallback-row select:visible, .submit-card input:visible, "
        ".submit-card textarea:visible, .reply-form textarea:visible, "
        ".option-choice:visible, .radio-mark:visible"
    )
    for element in page.locator(controls_selector).all():
        colors = element.evaluate("""el => {
          let parent = el.parentElement;
          while (parent &&
                 getComputedStyle(parent).backgroundColor === 'rgba(0, 0, 0, 0)') {
            parent = parent.parentElement;
          }
          return [getComputedStyle(el).borderTopColor, parent
            ? getComputedStyle(parent).backgroundColor
            : getComputedStyle(document.body).backgroundColor];
        }""")
        if page.locator("html").get_attribute("data-theme") == "dark":
            assert contrast_ratio(*colors) >= 3, (
                f"{path} control border contrast {colors}"
            )


def use_theme(page, origin, theme):
    page.emulate_media(color_scheme=theme)
    page.goto(f"{origin}/")
    page.evaluate("localStorage.clear(); sessionStorage.clear()")
    page.reload()
    assert page.locator("html").get_attribute("data-theme") == theme

    opposite = "dark" if theme == "light" else "light"
    page.goto(f"{origin}/settings/display")
    for target in (opposite, theme):
        page.get_by_role("radiogroup", name="Theme").get_by_role(
            "radio", name=target.capitalize()
        ).click()
        assert page.locator("html").get_attribute("data-theme") == target

    page.reload()
    assert page.locator("html").get_attribute("data-theme") == theme
    page.emulate_media(color_scheme=opposite)
    page.reload()
    assert page.locator("html").get_attribute("data-theme") == theme
    assert page.evaluate("localStorage.getItem('varde:theme')") == theme


def assert_desktop_plan_mail_contrast(page, origin, theme):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{origin}/plans")
    page.get_by_role("heading", name="Plans").wait_for()
    assert_page_text_contrast(page, "/plans needs-you 1440")
    assert_theme_surface_contrast(page, theme)
    assert_focus_contrast(page, "/plans needs-you 1440")


def assert_config_diff_contrast(page, origin):
    page.goto(f"{origin}/profile/builder")
    page.locator(".profile-screen").wait_for()
    assert_page_text_contrast(page, "/profile/builder")


def assert_focus_contrast(page, path):
    # Keyboard modality, so scripted focus() matches :focus-visible.
    page.keyboard.press("Shift")
    colors = page.evaluate("""() => {
      const selector = 'button:not(:disabled), a, summary, input:not(:disabled), textarea:not(:disabled), select:not(:disabled)';
      const visible = [...document.querySelectorAll(selector)].filter(el => {
        const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
        return el.getAttribute('href') !== '/new-item' && rect.width && rect.height && style.visibility !== 'hidden' &&
            style.display !== 'none' && el.checkVisibility() &&
            rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth &&
            rect.top < innerHeight;
      });
      return visible.map(el => {
        el.focus();
        let surface = el.parentElement;
        let background = surface ? getComputedStyle(surface).backgroundColor : 'transparent';
        while ((background === 'rgba(0, 0, 0, 0)' ||
               background === 'transparent') && surface?.parentElement) {
          surface = surface.parentElement;
          background = getComputedStyle(surface).backgroundColor;
        }
        const style = getComputedStyle(el);
        return [el.tagName, el.className, el.getAttribute('aria-label'), el.getAttribute('href'), el.textContent.trim(), style.outlineColor, background, style.outlineStyle];
      });
    }""")
    assert colors, f"{path} has no visible focusable elements"
    for tag, class_name, label, href, text, outline, background, style in colors:
        assert style != "none", f"{path} missing keyboard focus ring: {colors}"
        assert contrast_ratio(outline, background) >= 3, (
            f"{path} focus ring contrast for {(tag, class_name, label, href, text)}: "
            f"{(outline, background)}"
        )


@pytest.fixture
def browser_page(tmp_path, monkeypatch, browser_session, shared_browser_page):
    shared = {}
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    def make_app():
        app, cli, store = setup_app(tmp_path, monkeypatch)
        cli.extra_bindings = [{"address": "builder"}]
        cli.dashboard_app = app
        app.state.dashboard.read_cache.clear()
        reproject_messages(app)
        shared.update(app=app, cli=cli, store=store)
        return app

    config = uvicorn.Config(
        make_app,
        host="127.0.0.1",
        port=port,
        factory=True,
        log_level="error",
        access_log=False,
        lifespan="off",
        # test_server_shutdown.py covers graceful shutdown.
        timeout_graceful_shutdown=0,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    page = shared_browser_page
    browser_errors = {"console": [], "page": [], "requests": []}

    def record_console_error(message):
        expected_pairing_refusal = (
            message.type == "error"
            and "/api/pairing" in message.location.get("url", "")
            and "403" in message.text
        )
        if message.type == "error" and not expected_pairing_refusal:
            browser_errors["console"].append(f"{message.text} ({message.location})")

    page.on(
        "console",
        record_console_error,
    )
    page.on("pageerror", lambda error: browser_errors["page"].append(str(error)))
    page.on(
        "requestfailed",
        lambda request: (
            browser_errors["requests"].append(f"{request.url}: {request.failure}")
            if request.failure and "ERR_ABORTED" not in request.failure
            else None
        ),
    )
    page.route(
        "**/api/pairing",
        lambda route: route.fulfill(
            json={"enforced": False, "paired": True, "csrf": None}
        ),
    )
    page.route(
        "**/api/instance-threads?**", lambda route: route.fulfill(json={"threads": []})
    )
    page.route(
        "**/api/mail-soak",
        lambda route: route.fulfill(
            json={
                "date": "",
                "active_orchestrators": 0,
                "undeliverable": 0,
                "criteria": [],
            }
        ),
    )
    page.route(
        "**/api/workspaces", lambda route: route.fulfill(json={"workspaces": []})
    )
    page.route(
        "**/api/mailbox/*",
        lambda route: route.fulfill(
            json={
                "msg_id": route.request.url.rstrip("/").rsplit("/", 1)[-1],
                "mailbox_open": True,
            }
        ),
    )
    origin = f"http://127.0.0.1:{port}"
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/")
    page.evaluate("localStorage.clear(); sessionStorage.clear()")
    try:
        yield (page, browser_session, shared["store"], origin, shared["cli"])
    finally:
        assert not browser_errors["console"], browser_errors["console"]
        assert not browser_errors["page"], browser_errors["page"]
        assert not browser_errors["requests"], browser_errors["requests"]
        page.unroute_all(behavior="ignoreErrors")
        page.context.set_offline(False)
        page.goto("about:blank")
        stop_server(server, thread)
        shared["store"].close()


def test_phone_layout_and_plans_navigation(browser_page, browser_screenshot_dir):
    page, _, _, origin, _ = browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/")
    page.get_by_role("button", name="Open menu").wait_for(state="visible")
    assert page.get_by_role("button", name="Open menu").is_visible()
    page.get_by_role("button", name="Open menu").click()
    page.get_by_role("link", name="Plans").click()
    page.wait_for_url("**/plans")
    assert page.locator("body").evaluate("el => el.scrollWidth") <= 390
    assert page.get_by_role("heading", name="Plans", level=1).is_visible()


def test_plan_list_refreshes_on_focus_without_orchestrator_details(
    browser_page, browser_screenshot_dir
):
    page, _, _, origin, _ = browser_page
    calls = []

    def plans(route):
        calls.append(1)
        route.fulfill(
            json=[
                {
                    "id": "states",
                    "title": "Task progress states",
                    "label": "Task progress states",
                    "status": "in_progress",
                    "queue_position": None,
                    "open_comments": 0,
                    "updated": "2026-10-28T00:00:00Z",
                }
            ]
        )

    page.route("**/api/plans", plans)
    page.route(
        "**/events",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    for width, height in ((1280, 900), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        page.goto(f"{origin}/plans")
        row = page.get_by_role("link", name="Task progress states")
        row.wait_for()
        assert row.get_by_text("In progress", exact=True).count() == 0
        assert page.get_by_text("Task 1 building", exact=False).count() == 0
        page.screenshot(
            path=str(browser_screenshot_dir / f"plans-first-status-{width}.png"),
            full_page=True,
        )
        assert page.locator("body").evaluate("el => el.scrollWidth") <= width
    before = len(calls)
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    page.wait_for_function(
        "() => performance.getEntriesByName(location.origin + '/api/plans').length > 0"
    )
    page.wait_for_timeout(300)
    assert len(calls) > before


def test_plan_list_groups_active_queued_and_recently_done_plans(
    browser_page, browser_screenshot_dir
):
    page, _, _, origin, _ = browser_page
    rows = [
        {
            "id": "live",
            "title": "Live plan",
            "label": "Live plan",
            "status": "in_progress",
            "queue_position": None,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        },
        {
            "id": "queued",
            "title": "Queued plan",
            "label": "Queued plan",
            "status": "queued",
            "queue_position": 1,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        },
        {
            "id": "done",
            "title": "Finished plan",
            "label": "Finished plan",
            "status": "done",
            "queue_position": None,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        },
    ]
    page.route("**/api/plans", lambda route: route.fulfill(json=rows))
    page.route(
        "**/events",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{origin}/plans")
    page.wait_for_load_state("networkidle")
    assert page.get_by_role("heading", name="Plans", level=1).is_visible()
    live = page.get_by_role("link", name="Live plan")
    live.wait_for()
    assert live.get_by_text("In progress", exact=True).count() == 0
    queue = page.get_by_role("region", name="Queue")
    assert queue.get_by_role("link", name="Queued plan").is_visible()
    assert page.get_by_role("button", name="Move Queued plan up").count() == 1
    assert page.locator("details.done").get_attribute("open") is None
    page.screenshot(
        path=str(browser_screenshot_dir / "plans-first-list.png"), full_page=True
    )
    page.locator("details.done > summary").click()
    assert page.get_by_role("link", name="Finished plan").is_visible()
    assert page.get_by_role("button", name="Ask for status").count() == 0
    assert page.get_by_text("gaming-variants").count() == 0


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_mobile_dashboard_accessibility(
    tmp_path, monkeypatch, browser_server, shared_browser_page, request, theme
):
    status_plans = [
        {
            "id": "needs-input",
            "title": "Needs input",
            "label": "Needs input",
            "status": "needs_review",
            "queue_position": None,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        },
        {
            "id": "blocked",
            "title": "Blocked",
            "label": "Blocked",
            "status": "blocked",
            "queue_position": None,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        },
        {
            "id": "done",
            "title": "Done",
            "label": "Done",
            "status": "done",
            "queue_position": None,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        },
        {
            "id": "running",
            "title": "Running",
            "label": "Running",
            "status": "in_progress",
            "queue_position": None,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        },
        {
            "id": "queued",
            "title": "Queued",
            "label": "Queued",
            "status": "queued",
            "queue_position": 1,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        },
    ]
    app, _, store = setup_app(tmp_path, monkeypatch)
    request.addfinalizer(store.close)
    origin = browser_server(app)
    page = shared_browser_page
    page.route("**/api/plans", lambda route: route.fulfill(json=status_plans))
    page.route(
        "**/events",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.route(
        "**/api/instance-threads?**",
        lambda route: route.fulfill(
            json={
                "threads": [
                    {
                        "thread_key": "instance:builder",
                        "agent_id": "builder",
                        "plan_id": None,
                        "role": "builder",
                        "label": "Builder",
                        "state": "running",
                        "last_activity": None,
                    }
                ]
            }
        ),
    )
    use_theme(page, origin, theme)

    for width, height in ((390, 844), (1440, 900)):
        page.set_viewport_size({"width": width, "height": height})
        for path in (
            "/",
            "/thread/manager",
            "/thread/builder",
            "/profile/builder",
            "/plans",
        ):
            page.goto(f"{origin}{path}")
            page.wait_for_load_state("networkidle")
            if path == "/plans":
                assert (
                    page.locator('section[aria-label="In progress"]')
                    .get_by_role("link", name="Running")
                    .is_visible()
                )
                assert (
                    page.get_by_role("link", name="Blocked")
                    .locator(".badge")
                    .inner_text()
                    == "Blocked"
                )
                needs_review = page.get_by_role("region", name="Needs review")
                assert needs_review.get_by_role("link", name="Needs input").is_visible()
                queue = page.get_by_role("region", name="Queue")
                assert queue.get_by_role("link", name="Queued").is_visible()
                assert page.get_by_role("button", name="Move Queued up").count() == 1
                assert page.locator("details.done").get_attribute("open") is None
            dimensions_script = (
                "[document.documentElement.scrollWidth, "
                "document.documentElement.clientWidth]"
            )
            dimensions = page.evaluate(dimensions_script)
            assert dimensions[0] <= dimensions[1], (
                f"{path} overflows at {width}px: {dimensions}"
            )

            assert_page_text_contrast(page, path)
            assert_theme_surface_contrast(page, theme)
            assert_focus_contrast(page, path)

            targets_selector = (
                "button:visible, a:visible, summary:visible, "
                "input:visible:not([type=checkbox]), textarea:visible, "
                "select:visible, label.choice:visible:has(input[type=checkbox])"
            )
            targets_script = (
                "els => els.filter(el => !el.disabled).map(el => [el.tagName, "
                "el.getBoundingClientRect().width, "
                "el.getBoundingClientRect().height, el.innerText])"
            )
            targets = page.locator(targets_selector).evaluate_all(targets_script)
            assert all(
                width >= 44 and height >= 44
                for _, width, height, label in targets
                if label.strip() != "Edit"
            ), f"{path} small touch target: {targets}"

        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{origin}/plans")
        page.get_by_role("heading", name="Plans").wait_for()
        assert_focus_contrast(page, "/plans needs-you")
        page.get_by_role("button", name="Open menu").click()
        links = page.get_by_role("dialog").get_by_role("link")
        assert links.count() == 3
        assert all(link.bounding_box()["height"] >= 44 for link in links.all())
        page.get_by_role("button", name="Close menu").click()

        assert_desktop_plan_mail_contrast(page, origin, theme)
        assert_config_diff_contrast(page, origin)


@pytest.mark.parametrize("width,height", [(390, 844), (1440, 900)])
def test_spa_shell_and_dashboard_pages(
    browser_page, browser_screenshot_dir, width, height
):
    page, _, _, origin, cli = browser_page
    cli.plan = {
        "plans": [
            {
                "id": "plan-1",
                "status": "active",
                "assigned_to": "builder",
                "title": "Plan One",
            }
        ]
    }
    cli.extra_bindings = [{"address": "builder", "plan_id": "plan-1"}]
    cli.messages = []
    cli.dashboard_app.state.dashboard.read_cache.clear()
    cli.dashboard_app.state.dashboard.snapshot_loaded_at = 0
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{origin}/")
    page.get_by_role("heading", name="Chats").wait_for()
    if width < 900:
        page.locator(".chat-list .empty").wait_for(state="visible")
    else:
        page.locator(".desktop-chat-sidebar").get_by_text(
            "No conversations yet"
        ).wait_for(state="visible")
    page.locator(".pin-section .needs-action").wait_for(state="detached")
    if width < 900:
        assert page.get_by_role("button", name="Open menu").is_visible()
        page.get_by_role("button", name="Open menu").click()
        nav = page.get_by_role("navigation", name="Main menu")
        for label in ("Conversations", "Plans", "Settings"):
            assert nav.get_by_role("link", name=label).is_visible()
        page.get_by_role("button", name="Close menu").click()
    else:
        assert page.get_by_role("button", name="Open menu").count() == 1
    page.screenshot(
        path=str(browser_screenshot_dir / f"c1a-orchestrators-{width}.png"),
        full_page=True,
    )
    page.goto(f"{origin}/plans")
    page.get_by_role("heading", name="Plans", level=1).wait_for()
    page.goto(f"{origin}/thread/manager")
    page.get_by_role("heading").first.wait_for()
    assert page.locator("body").evaluate("el => el.scrollWidth") <= width
    page.screenshot(
        path=str(browser_screenshot_dir / f"c1a-threads-{width}.png"), full_page=True
    )


def test_new_inbox_item_appears_from_sse_without_page_reload(browser_page, tmp_path):
    page, _, _, origin, _ = browser_page
    state = {
        "threads": [],
        "mailbox": {"open": [], "all": [], "resolved": [], "permissions": []},
    }
    page.route("**/api/threads", lambda route: route.fulfill(json=state["threads"]))
    page.route(
        "**/api/mailbox?**",
        lambda route: route.fulfill(json={"items": state["mailbox"].get("all", [])}),
    )
    page.goto(f"{origin}/")
    load_count = page.evaluate("performance.getEntriesByType('navigation').length")
    item = {
        "msg_id": "question-streamed",
        "sender": "builder",
        "title": "Streamed question",
        "asked": "Streamed question",
        "kind": "needs-user",
        "state": "pending",
        "mailbox_open": True,
        "ts": "2099-10-21T10:00:00Z",
    }
    state["threads"] = [
        {
            "thread_id": "sender:varde-builder",
            "plan_id": None,
            "sender": "varde-builder",
            "title": "Streamed question",
            "open_count": 1,
            "last_ts": item["ts"],
            "last_preview": "Streamed question",
            "decision_ids": [item["msg_id"]],
            "user_message": True,
        }
    ]
    state["mailbox"] = {
        "open": [item],
        "all": [item],
        "resolved": [],
        "permissions": [],
    }
    page.evaluate(
        "topics => dispatchEvent(new CustomEvent('runner:snapshot', "
        "{detail: {topics}}))",
        ["mailbox"],
    )
    page.locator(".chat-row").filter(has_text="Streamed question").wait_for(
        timeout=10000
    )
    assert (
        page.evaluate("performance.getEntriesByType('navigation').length") == load_count
    )


def test_plan_status_updates_from_events_without_navigation(browser_page):
    page, _, _, origin, _ = browser_page
    row = {
        "id": "live-status",
        "title": "Live status fixture",
        "label": "Live status fixture",
        "status": "queued",
        "queue_position": 1,
        "open_comments": 0,
        "updated": "2026-10-28T00:00:00Z",
    }
    state = {"rows": [row]}
    page.route("**/api/plans", lambda route: route.fulfill(json=state["rows"]))
    page.route(
        "**/events",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.goto(f"{origin}/plans")
    plan = page.get_by_role("link", name="Live status fixture")
    page.get_by_role("region", name="Queue").get_by_role(
        "link", name="Live status fixture"
    ).wait_for()
    state["rows"] = [{**row, "status": "in_progress", "queue_position": None}]
    page.evaluate(
        "topics => window.dispatchEvent(new CustomEvent('runner:snapshot', {detail: {topics}}))",
        ["plans"],
    )
    page.get_by_role("region", name="In progress").wait_for()
    assert plan.get_by_text("In progress", exact=True).count() == 0
    assert page.url == f"{origin}/plans"


def test_queue_positions_refresh_without_navigation(browser_page):
    page, _, _, origin, _ = browser_page
    rows = [
        {
            "id": "queued-a",
            "title": "Queued A",
            "label": "Queued A",
            "status": "queued",
            "queue_position": 1,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        },
        {
            "id": "queued-b",
            "title": "Queued B",
            "label": "Queued B",
            "status": "queued",
            "queue_position": 2,
            "open_comments": 0,
            "updated": "2026-10-28T00:00:00Z",
        },
    ]
    state = {"rows": rows}
    page.route("**/api/plans", lambda route: route.fulfill(json=state["rows"]))
    page.route(
        "**/events",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.goto(f"{origin}/plans")
    queue = page.get_by_role("region", name="Queue")
    queue.get_by_role("link", name="Queued A").wait_for()
    page.wait_for_function(
        """() => [...document.querySelectorAll('[aria-label="Queue"] .copy .title')]
          .map(node => node.textContent).join('|') === 'Queued A|Queued B'"""
    )
    state["rows"] = [rows[1] | {"queue_position": 1}, rows[0] | {"queue_position": 2}]
    page.evaluate(
        "topics => window.dispatchEvent(new CustomEvent('runner:snapshot', {detail: {topics}}))",
        ["plans"],
    )
    page.wait_for_function(
        """() => [...document.querySelectorAll('[aria-label="Queue"] .copy .title')]
          .map(node => node.textContent).join('|') === 'Queued B|Queued A'"""
    )
    assert page.url == f"{origin}/plans"


def test_needs_you_shows_retry_after_permission_answer_fails(browser_page):
    page, _, _, origin, _ = browser_page
    page.set_viewport_size({"width": 1440, "height": 900})
    permission = {
        "msg_id": "permission-1",
        "sender": "builder",
        "title": "Permission?",
        "asked": "Permission?",
        "why": "Approve",
        "kind": "permission",
        "state": "pending",
        "ts": "2099-10-23T10:00:00Z",
    }
    page.route(
        "**/api/threads",
        lambda route: route.fulfill(
            json=[
                {
                    "thread_id": "sender:varde-builder",
                    "plan_id": None,
                    "sender": "varde-builder",
                    "title": "Permission?",
                    "open_count": 1,
                    "last_ts": permission["ts"],
                    "last_preview": "Permission?",
                    "decision_ids": ["permission-1"],
                    "user_message": True,
                }
            ]
        ),
    )
    page.route(
        "**/api/mailbox?**",
        lambda route: route.fulfill(
            json={"items": [{**permission, "mailbox_open": True}]}
        ),
    )
    page.route(
        "**/api/mailbox/permission-1",
        lambda route: route.fulfill(json={**permission, "mailbox_open": True}),
    )
    page.route(
        "**/api/mailbox/permission-1/answer",
        # Exercise the app's explicit failed-answer state without a browser-level
        # HTTP error, which the shared fixture correctly reports as console noise.
        lambda route: route.fulfill(json={"status": "failed"}),
    )
    page.goto(f"{origin}/")
    row = page.locator(".desktop-chat-sidebar .row").filter(has_text="Permission?")
    row.wait_for()
    assert row.get_attribute("href") == "/threads/sender%3Avarde-builder"
    page.goto(f"{origin}/threads/sender%3Avarde-builder")
    page.locator(".app-header .title").wait_for()
    page.get_by_role("button", name="Allow").click()
    page.get_by_role("status").filter(has_text="Failed").wait_for()
    assert page.get_by_role("button", name="Retry").is_visible()
