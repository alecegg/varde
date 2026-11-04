from __future__ import annotations

import re

import pytest
import test_web_browser
from test_web_browser import contrast_ratio

pytestmark = pytest.mark.slow

browser_page = test_web_browser.browser_page


TOLERANCE = 0.5


def test_mobile_header_status_is_visible_symmetric_and_has_large_targets(browser_page):
    page, _, _, origin, _ = browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/")
    header = page.locator(".app-header")
    action = page.locator("a.action")
    header.wait_for()
    assert header.locator(".health").count() == 0
    assert page.get_by_text("Online", exact=True).count() == 0
    assert action.bounding_box()["width"] >= 44
    assert action.bounding_box()["height"] >= 44
    title = page.locator(".title-group").bounding_box()
    header_box = header.bounding_box()
    assert abs((title["x"] + title["width"] / 2) - 195) <= TOLERANCE
    assert header_box["width"] == 390


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_desktop_empty_state_focus_ring_uses_theme_text_token(browser_page, theme):
    page, _, _, origin, _ = browser_page
    page.emulate_media(color_scheme=theme)
    page.goto(f"{origin}/")
    page.evaluate("localStorage.removeItem('varde:theme')")
    page.reload()
    for width, name in ((390, "Start a chat"), (1440, "Start a new conversation")):
        page.set_viewport_size({"width": width, "height": 900})
        link = page.get_by_role("link", name=name)
        link.wait_for(state="visible")
        page.keyboard.press("Shift")
        link.focus()
        styles = link.evaluate("""element => {
          const style = getComputedStyle(element);
          const probe = document.createElement('span');
          probe.style.color = getComputedStyle(element).getPropertyValue('--cf-text');
          document.body.append(probe);
          const expected = getComputedStyle(probe).color;
          probe.remove();
          const shell = document.querySelector('.chat-shell');
          return {
            outline: style.outlineColor,
            outlineStyle: style.outlineStyle,
            expected,
            background: getComputedStyle(shell).backgroundColor
          };
        }""")
        assert styles["outlineStyle"] != "none", styles
        assert styles["outline"] == styles["expected"], styles
        assert contrast_ratio(styles["outline"], styles["background"]) >= 3, styles


def test_menu_respects_reduced_motion(browser_page):
    page, _, _, origin, _ = browser_page
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{origin}/")
    page.get_by_role("button", name="Open menu").click()
    page.get_by_role("dialog").wait_for()
    assert (
        page.locator(".menu-panel").evaluate(
            "element => getComputedStyle(element).animationName"
        )
        == "none"
    )
    assert (
        page.locator(".menu-scrim").evaluate(
            "element => getComputedStyle(element).animationName"
        )
        == "none"
    )


def test_menu_trigger_reports_open_state_and_gets_focus_on_close(browser_page):
    page, _, _, origin, _ = browser_page
    page.goto(f"{origin}/")
    trigger = page.get_by_role("button", name="Open menu")
    assert trigger.get_attribute("aria-haspopup") == "dialog"
    assert trigger.get_attribute("aria-expanded") == "false"
    trigger.click()
    page.get_by_role("dialog").wait_for()
    assert trigger.get_attribute("aria-expanded") == "true"
    page.get_by_role("button", name="Close menu").click()
    page.wait_for_function(
        "document.querySelector('.menu-button')?.getAttribute('aria-expanded') "
        "=== 'false'"
    )
    assert trigger.evaluate("button => document.activeElement === button")


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= TOLERANCE


def _measure_chips(page):
    return page.locator(".avatars .chip").evaluate_all("""chips => chips.map(chip => {
      const box = element => {
        const r = element.getBoundingClientRect();
        return {
          x: r.x, y: r.y, width: r.width, height: r.height,
          right: r.right, bottom: r.bottom
        };
      };
      const circle = chip.querySelector('.circle');
      const label = chip.querySelector('.label');
      const style = getComputedStyle(label);
      const avatar = circle.matches('.running,.queued,.needs-you');
      const indicatorStyle = avatar && getComputedStyle(circle, '::after');
      const badge = chip.querySelector('.count');
      const circleBox = circle.getBoundingClientRect();
      const indicator = badge ? box(badge) : avatar ? {
        x: circleBox.right - parseFloat(indicatorStyle.width),
        y: circleBox.bottom - parseFloat(indicatorStyle.height),
        width: parseFloat(indicatorStyle.width),
        height: parseFloat(indicatorStyle.height),
        right: circleBox.right, bottom: circleBox.bottom
      } : null;
      return {
        name: label.textContent.trim(),
        initials: circle.querySelector('.initials')?.textContent.trim(),
        avatarImage: getComputedStyle(circle).backgroundImage,
        indicatorBorderWidth: indicatorStyle?.borderWidth,
        indicatorBorderColor: indicatorStyle?.borderColor,
        chip: box(chip), circle: box(circle),
        label: box(label), fontSize: style.fontSize,
        fontWeight: style.fontWeight, indicator
      };
    })""")


def _verify_chips(page, theme: str):
    metrics = _measure_chips(page)
    assert metrics, f"{theme}: no avatar chips found"
    assert [(item["name"], item["initials"]) for item in metrics[1:]] == [
        ("Manager", "MG"),
        ("Builder", "BU"),
        ("Reviewer", "RE"),
    ], metrics
    assert [item["avatarImage"] for item in metrics[1:]] == [
        "linear-gradient(135deg, rgb(116, 72, 215), rgb(67, 35, 149))",
        "linear-gradient(135deg, rgb(39, 99, 180), rgb(18, 59, 122))",
        "linear-gradient(135deg, rgb(22, 122, 73), rgb(13, 77, 49))",
    ], metrics
    assert (
        page.locator(".chip[href='/thread/manager']").evaluate(
            "chip => getComputedStyle(chip, '::after').content"
        )
        == "none"
    )
    menu = page.locator(".menu-button")
    assert menu.inner_text() == "☰"
    assert menu.evaluate("button => getComputedStyle(button).fontSize") == "20px"
    first = metrics[0]
    assert _close(first["chip"]["width"], 64), first
    assert _close(first["chip"]["height"], 84), first
    assert _close(first["circle"]["width"], 52), first
    assert _close(first["circle"]["height"], 52), first
    assert first["fontSize"] == "12px", first
    assert first["fontWeight"] == "600", first
    assert _close(first["label"]["height"], 16), first
    for item in metrics:
        for key in ("chip", "circle"):
            for dimension in ("width", "height"):
                assert _close(item[key][dimension], first[key][dimension]), item
        assert item["fontSize"] == first["fontSize"], item
        assert item["fontWeight"] == first["fontWeight"], item
        assert _close(item["label"]["height"], first["label"]["height"]), item
        if item["indicator"]:
            marker = item["indicator"]
            assert marker["x"] >= item["chip"]["x"] - TOLERANCE, item
            assert marker["y"] >= item["chip"]["y"] - TOLERANCE, item
            assert marker["right"] <= item["chip"]["right"] + TOLERANCE, item
            assert marker["bottom"] <= item["chip"]["bottom"] + TOLERANCE, item
            if item["indicatorBorderWidth"]:
                assert item["indicatorBorderWidth"] == "2px", item
                assert _close(marker["width"], 14), item
                assert _close(marker["height"], 14), item
    badge = page.locator(".needs-chip .count")
    assert badge.count() == 1
    chip_box, badge_box = (
        page.locator(".needs-chip").bounding_box(),
        badge.bounding_box(),
    )
    assert chip_box and badge_box
    assert (
        badge_box["x"] + badge_box["width"]
        <= chip_box["x"] + chip_box["width"] + TOLERANCE
    )
    assert badge_box["x"] + badge_box["width"] >= chip_box["x"] + chip_box["width"] - 24
    assert badge_box["y"] >= chip_box["y"] - 1
    assert badge_box["y"] <= chip_box["y"] + 4


def _verify_menu(page, theme: str):
    panel = page.locator(".menu-panel")
    assert panel.is_visible(), theme
    labels = [
        re.sub(r"\s+", " ", text).strip()
        for text in page.locator(".menu-links a").all_inner_texts()
    ]
    assert labels == [
        "Conversations",
        "Plans",
        "Settings",
    ]
    assert panel.evaluate("node => getComputedStyle(node).fontFamily") == (
        "system-ui, -apple-system, sans-serif"
    )
    assert (
        page.locator(".menu-heading").evaluate(
            "node => getComputedStyle(node).fontWeight"
        )
        == "700"
    )
    assert panel.evaluate("node => getComputedStyle(node).backgroundColor") == (
        "rgb(255, 255, 255)" if theme == "light" else "rgb(22, 23, 28)"
    )


def _install_fakes(page):
    page.route("**/api/**", lambda route: route.fulfill(json={}))
    roles = [
        {"role": "manager-bot", "state": "running", "queued": 0, "needs_you": 0},
        {"role": "builder", "state": "needs_you", "queued": 1, "needs_you": 1},
        {"role": "reviewer", "state": "running", "queued": 0, "needs_you": 0},
    ]
    page.route("**/api/home", lambda route: route.fulfill(json={"roles": roles}))
    page.route(
        "**/api/roles",
        lambda route: route.fulfill(json={"roles": {"manager-bot": {"enabled": True}}}),
    )
    page.route(
        "**/api/needs-you-count",
        lambda route: route.fulfill(json={"needs_you_count": 1}),
    )
    page.route("**/api/settings", lambda route: route.fulfill(json={"app_icon": ""}))
    page.route(
        "**/api/instance-threads",
        lambda route: route.fulfill(json={"threads": []}),
    )
    page.route(
        "**/api/pairing",
        lambda route: route.fulfill(
            json={"enforced": False, "paired": True, "csrf": None}
        ),
    )
    page.route("**/api/threads", lambda route: route.fulfill(json=[]))
    page.route(
        "**/api/instance-threads**",
        lambda route: route.fulfill(json={"threads": []}),
    )
    page.route("**/api/mailbox?**", lambda route: route.fulfill(json={"items": []}))
    page.route(
        "**/api/agents",
        lambda route: route.fulfill(
            json=[
                {
                    "agent_id": "manager-child",
                    "harness": "codex",
                    "role": "builder",
                    "workspace": "varde-py",
                    "lifecycle": "running",
                    "idle_status": None,
                    "root_launched_by": "bot:manager",
                    "capabilities": {"respond": True},
                    "pending_requests": [
                        {
                            "request_id": "manager-child-request",
                            "kind": "permission",
                            "summary": "Read access to varde-py working tree",
                        }
                    ],
                }
            ]
        ),
    )
    page.route("**/api/degraded", lambda route: route.fulfill(json={"sources": []}))
    page.route(
        "**/api/queue/roles/**",
        lambda route: route.fulfill(
            json={
                "summary": {
                    "role": "manager-bot",
                    "state": "running",
                    "current": {"title": "visual checks"},
                    "queued": 2,
                    "needs_you": 0,
                }
            }
        ),
    )
    page.route(
        "**/api/chat/stream**",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.route("**/api/chat/audit**", lambda route: route.fulfill(json=[]))
    page.route(
        "**/api/chat?**",
        lambda route: route.fulfill(
            json={
                "messages": [],
                "latest_seq": 0,
                "thread": {
                    "key": "main",
                    "kind": "main",
                    "label": None,
                    "state": "active",
                },
                "bot": {"state": "ready", "context_pct": None, "generation": 0},
            }
        ),
    )
    page.route(
        "**/api/threads/**",
        lambda route: route.fulfill(
            json={
                "agent_id": "builder",
                "label": "Builder",
                "role": "builder",
                "state": "running",
            }
        ),
    )
    page.route(
        "**/api/identities",
        lambda route: route.fulfill(
            json={
                "identities": [
                    {
                        "id": "builder",
                        "name": "Builder",
                        "label": "Builder",
                        "role": "builder",
                        "description": "",
                        "count": 1,
                        "worst_state": "running",
                        "instances": [],
                    }
                ]
            }
        ),
    )
    page.route(
        "**/api/instance-threads**",
        lambda route: route.fulfill(
            json={
                "threads": [
                    {
                        "agent_id": "builder",
                        "label": "Builder",
                        "role": "builder",
                        "state": "running",
                    }
                ]
            }
        ),
    )
    page.route("**/api/bot/**", lambda route: route.fulfill(json=[]))
    page.route(
        "**/api/events",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.route(
        "**/events",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )


def _check_button_colors(page, path: str):
    colors = page.evaluate("""() => {
      const root = getComputedStyle(document.documentElement);
      const probe = document.createElement('i');
      document.body.append(probe);
      const resolve = property => {
        probe.style.backgroundColor = root.getPropertyValue(property).trim();
        return getComputedStyle(probe).backgroundColor;
      };
      const buttons = [...document.querySelectorAll('button, a[role=button]')]
        .filter(el => {
          const r = el.getBoundingClientRect();
          return r.width && r.height;
        })
        .map(el => {
          const style = getComputedStyle(el);
          return {
            text: el.innerText.trim(), className: String(el.className),
            color: style.color, background: style.backgroundColor
          };
      });
      const amber = resolve('--cf-accent');
      const primary = resolve('--cf-primary');
      probe.style.color = root.getPropertyValue('--cf-primary-ink').trim();
      const primaryInk = getComputedStyle(probe).color;
      const soft = resolve('--cf-soft');
      const bad = resolve('--cf-bad');
      probe.style.color = root.getPropertyValue('--cf-text').trim();
      const text = getComputedStyle(probe).color;
      const amberSurfaces = [...document.querySelectorAll('body *')].filter(el => {
        const r = el.getBoundingClientRect();
        return r.width && r.height && getComputedStyle(el).backgroundColor === amber;
      }).map(el =>
        el.matches('.circle,.state-dot') || el.closest('.circle,.state-dot')
      );
      return { buttons, amber, primary, primaryInk, soft, bad, text, amberSurfaces };
    }""")
    for item in colors["buttons"]:
        name = item["className"]
        if "primary" in name or "send" in name.split():
            assert (
                item["background"] == colors["primary"]
                and item["color"] == colors["primaryInk"]
            ), (path, item, colors)
        if "secondary" in name:
            expected_color = colors["bad"] if "danger" in name else colors["text"]
            assert (
                item["background"] == colors["soft"] and item["color"] == expected_color
            ), (path, item, colors)
    assert all(colors["amberSurfaces"]), (path, colors["amberSurfaces"])


def _check_text_contrast(page, path: str):
    colors = page.evaluate("""() => {
      const root = getComputedStyle(document.documentElement);
      const probe = document.createElement('span'); document.body.append(probe);
      const resolve = name => {
        probe.style.color = root.getPropertyValue(name).trim();
        return getComputedStyle(probe).color;
      };
      const bg = root.getPropertyValue('--cf-bg').trim();
      probe.style.color = root.getPropertyValue('--cf-text').trim();
      return {
        text: getComputedStyle(probe).color,
        muted: resolve('--cf-muted'), background: bg
      };
    }""")
    background = page.locator("html").evaluate(
        "el => getComputedStyle(el).backgroundColor"
    )
    assert contrast_ratio(colors["text"], background) >= 4.5, (path, colors, background)
    assert contrast_ratio(colors["muted"], background) >= 4.5, (
        path,
        colors,
        background,
    )


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_chat_first_visual_metrics_and_screen_requests(browser_page, theme, tmp_path):
    page, _, _, origin, _ = browser_page
    errors, failed = [], []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.on(
        "requestfailed",
        lambda request: failed.append(
            f"{request.method} {request.url}: {request.failure}"
        ),
    )
    _install_fakes(page)
    page.set_viewport_size({"width": 390, "height": 844})
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{origin}/")
    page.evaluate(
        """theme => {
          document.documentElement.dataset.theme = theme;
          localStorage.setItem('varde:theme', theme);
        }""",
        theme,
    )
    page.reload()
    assert page.locator("html").get_attribute("data-theme") == theme
    page.get_by_role("heading", name="Chats").wait_for()
    page.locator(".pin-section .needs-action").wait_for()
    _check_text_contrast(page, "/")
    assert page.locator(".app-header .title").inner_text() == "Chats"
    assert page.locator("body").evaluate("el => el.scrollWidth") <= 390
    page.screenshot(path=str(tmp_path / f"app-home-{theme}.png"), full_page=True)
    page.get_by_role("button", name="Open menu").click()
    page.get_by_role("dialog").wait_for()
    _verify_menu(page, theme)
    page.get_by_role("button", name="Close menu").click()

    routes = ["/thread/manager", "/thread/builder", "/profile/builder"]
    for path in routes:
        page.goto(f"{origin}{path}")
        if path == "/thread/manager":
            header = page.locator(".app-header")
            assert header.locator(".title").inner_text() == "Manager"
            assert header.locator(".health").count() == 0
            card = page.locator(".messages [data-testid='inline-approval']")
            card.wait_for()
            assert card.get_by_role("button", name="Allow").is_visible()
            assert card.get_by_role("button", name="Deny").is_visible()
            page.get_by_role("textbox", name="Message Manager…").wait_for()
            _check_text_contrast(page, path)
            card = page.get_by_role("link", name="Working on visual checks, 2 in queue")
            if card.count():
                assert card.is_visible()
        if path.startswith("/profile/"):
            page.get_by_role("heading", name="Builder").wait_for()
        page.get_by_role("button", name="Open menu").click()
        page.get_by_role("dialog").wait_for()
        _verify_menu(page, theme)
        page.get_by_role("button", name="Close menu").click()
        assert page.locator("body").evaluate("el => el.scrollWidth") <= 390, path
    assert not errors, f"console errors: {errors}"
    assert not failed, f"failed requests: {failed}"


@pytest.mark.parametrize("width", [320, 390, 768, 899, 900, 1440])
def test_chats_show_only_user_replies_without_horizontal_overflow(
    browser_page, width, tmp_path
):
    page, _, _, origin, _ = browser_page
    _install_fakes(page)
    page.route(
        "**/api/threads",
        lambda route: route.fulfill(
            json=[
                {
                    "thread_id": "plan:internal-update",
                    "plan_id": "internal-update",
                    "sender": "builder",
                    "plan_title": "Agent to agent update",
                    "title": "Private work note",
                    "open_count": 1,
                    "last_ts": "2099-01-01T00:00:00Z",
                    "last_preview": "Automated relay content",
                    "user_message": False,
                },
                {
                    "thread_id": "sender:automated-relay",
                    "plan_id": None,
                    "sender": "automated-relay",
                    "title": "Automated relay",
                    "open_count": 1,
                    "last_ts": "2099-01-01T00:00:00Z",
                    "last_preview": "Agent-only content",
                    "user_message": False,
                },
                {
                    "thread_id": "plan:user-reply",
                    "plan_id": "user-reply",
                    "sender": "builder",
                    "plan_title": "User reply plan",
                    "title": "Answer to user",
                    "open_count": 0,
                    "last_ts": "2099-01-01T00:00:00Z",
                    "last_preview": "Here is the answer",
                    "user_message": True,
                },
                {
                    "thread_id": "sender:user-reply",
                    "plan_id": None,
                    "sender": "builder",
                    "title": "User reply from builder",
                    "open_count": 0,
                    "last_ts": "2099-01-01T00:00:00Z",
                    "last_preview": "Here is the response",
                    "user_message": True,
                },
            ]
        ),
    )
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{origin}/")
    if width >= 900:
        rows = page.locator(".desktop-chat-sidebar .rows")
        rows.wait_for(state="visible")
        reply_rows = rows.locator("a[href^='/threads/']")
    else:
        page.get_by_role("heading", name="Chats").wait_for()
        rows = page.locator(".chat-list main")
        reply_rows = rows.locator("a.chat-row[href^='/threads/']")
    rows.locator("a[href='/threads/plan%3Auser-reply']").wait_for()
    assert reply_rows.count() == 2
    assert reply_rows.evaluate_all(
        "nodes => nodes.map(node => node.getAttribute('href')).sort()"
    ) == ["/threads/plan%3Auser-reply", "/threads/sender%3Auser-reply"]
    assert page.get_by_text("Agent to agent update").count() == 0
    assert page.get_by_text("Automated relay").count() == 0
    assert page.locator('a[href="/mailbox"], a[href="/threads"]').count() == 0
    assert page.locator("body").evaluate("el => el.scrollWidth") <= width
    if width in {390, 1440}:
        page.screenshot(path=str(tmp_path / f"chat-home-{width}.png"), full_page=True)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_empty_conversation_list(browser_page, theme):
    page, _, _, origin, _ = browser_page
    _install_fakes(page)
    page.route("**/api/home", lambda route: route.fulfill(json={"roles": []}))
    page.route("**/api/threads", lambda route: route.fulfill(json=[]))
    page.route("**/api/agents", lambda route: route.fulfill(json=[]))
    page.route(
        "**/api/instance-threads**", lambda route: route.fulfill(json={"threads": []})
    )
    page.emulate_media(color_scheme=theme, reduced_motion="reduce")
    for width, height in ((390, 844), (1440, 900)):
        page.set_viewport_size({"width": width, "height": height})
        page.goto(f"{origin}/")
        if width < 900:
            empty = page.locator(".empty")
            empty_box = empty.bounding_box()
            assert empty_box and empty_box["width"] > 0 and empty_box["height"] > 0
            assert empty.locator("strong").inner_text() == "No conversations yet"
            assert empty.get_by_role("link", name="Start a chat").is_visible()
        else:
            empty = page.locator(".desktop-empty-state")
            empty.wait_for(state="visible")
            assert empty.get_by_text(
                "Select a conversation or start a new one"
            ).is_visible()
            assert empty.get_by_role(
                "link", name="Start a new conversation"
            ).is_visible()
        page.locator(".needs-action").wait_for(state="detached")
