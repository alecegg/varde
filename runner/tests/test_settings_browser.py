from __future__ import annotations

import pytest
from playwright.sync_api import expect
from varde_runner.web import create_app
from varde_runner.web.settings import read_settings

pytestmark = pytest.mark.slow


class FakeCLI:
    def read_messages(self):
        return []

    def read_plan(self):
        return {"plans": []}

    def read_address_bindings(self):
        return []

    def send(self, **kwargs):
        return {"id": "message-1"}

    def acknowledge(self, message_id, *, address):
        return None


def start(browser_server, tmp_path):
    app = create_app(data_dir=tmp_path, cli=FakeCLI())
    return browser_server(app), app


def test_settings_page_uses_fixed_light_and_dark_icons(
    browser_server, shared_browser_page, tmp_path
):
    origin, app = start(browser_server, tmp_path)
    page = shared_browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    response = page.goto(f"{origin}/settings")
    page.get_by_role("heading", name="Settings").wait_for()
    assert response is not None
    html = response.text()
    assert html.count('rel="icon" type="image/svg+xml" href="/favicon.svg"') == 1
    assert read_settings(app.state.settings_path) == {"app_icon": "slate-bronze"}
    assert page.get_by_text("App icon", exact=True).count() == 0
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_settings_navigation_drills_in_and_returns_to_overview(
    browser_server, shared_browser_page, tmp_path
):
    origin, _ = start(browser_server, tmp_path)
    page = shared_browser_page
    for width in (390, 1280):
        for theme in ("light", "dark"):
            page.set_viewport_size({"width": width, "height": 844})
            page.emulate_media(color_scheme=theme)
            page.goto(f"{origin}/settings")
            navigation = page.get_by_role("navigation", name="Settings sections")
            rows = navigation.locator("a[data-settings-row]")
            rows.first.wait_for()
            assert rows.count() == 7
            assert page.locator(".app-header").count() == 1
            assert page.locator(".shell-header").count() == 0
            assert page.get_by_role("button", name="Open menu").count() == 1
            assert page.evaluate(
                "document.documentElement.scrollWidth <= "
                "document.documentElement.clientWidth"
            )
            assert page.locator(".settings-content textarea:visible").count() == 0
            for index in range(rows.count()):
                row = rows.nth(index)
                assert row.bounding_box()["height"] >= 48
                section = row.get_attribute("data-settings-row")
                if section == "roles":
                    assert row.get_attribute("href") == "/roles"
                    continue
                row.click()
                page.wait_for_url(f"**/settings/{section}")
                page.get_by_role(
                    "heading", name=section.replace("-", " "), exact=False
                ).first.wait_for()
                expected_sections = {section}
                for section_id in (
                    "harnesses",
                    "runner",
                    "model-types",
                    "display",
                    "review",
                    "status",
                ):
                    assert page.locator(f"#{section_id}").is_visible() == (
                        section_id in expected_sections
                    )
                assert (
                    page.get_by_role("link", name="Back to settings").get_attribute(
                        "href"
                    )
                    == "/settings"
                )
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= "
                    "document.documentElement.clientWidth"
                )
                if section in {"display", "review", "status"}:
                    groups = page.locator(
                        ".settings-content .settings-anchor > .section"
                    )
                    assert groups.count() >= 1
                    assert (
                        groups.first.evaluate(
                            "element => getComputedStyle(element).borderTopWidth"
                        )
                        == "0px"
                    )
                    assert (
                        groups.first.evaluate(
                            "element => getComputedStyle(element).backgroundColor"
                        )
                        == "rgba(0, 0, 0, 0)"
                    )
                header = page.locator(".chat-shell > .app-header")
                header_bounds = header.bounding_box()
                assert header_bounds["x"] == (0 if width < 900 else 320)
                assert header_bounds["y"] == 0
                assert header_bounds["x"] + header_bounds["width"] <= width
                page.get_by_role("link", name="Back to settings").click()
                page.get_by_role("navigation", name="Settings sections").wait_for()


def test_legacy_settings_hash_redirects_to_section(
    browser_server, shared_browser_page, tmp_path
):
    origin, _ = start(browser_server, tmp_path)
    page = shared_browser_page
    page.goto(f"{origin}/settings#runner")
    page.wait_for_url("**/settings/runner")
    page.get_by_role("heading", name="Runner").first.wait_for()
    assert page.get_by_role("heading", name="Runner").first.is_visible()


def test_desktop_settings_navigation_uses_plain_grouped_rows(
    browser_server, shared_browser_page, tmp_path
):
    origin, _ = start(browser_server, tmp_path)
    page = shared_browser_page
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{origin}/settings")
    nav = page.locator("nav.settings-nav")
    assert (
        nav.evaluate("element => getComputedStyle(element).backgroundColor")
        == "rgba(0, 0, 0, 0)"
    )
    assert nav.evaluate("element => getComputedStyle(element).padding") == "0px"


def test_settings_theme_section_switches_theme(
    browser_server, shared_browser_page, tmp_path
):
    origin, _ = start(browser_server, tmp_path)
    page = shared_browser_page
    page.goto(f"{origin}/settings/display")
    page.get_by_role("radiogroup", name="Theme").get_by_role(
        "radio", name="Dark"
    ).click()
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    page.get_by_role("radiogroup", name="Theme").get_by_role(
        "radio", name="Light"
    ).click()
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    assert page.evaluate("localStorage.getItem('varde:theme')") == "light"
    page.evaluate("localStorage.clear()")


def test_settings_icon_choice_persists_and_updates_manifest_and_touch_icon(
    browser_server, shared_browser_page, tmp_path
):
    origin, app = start(browser_server, tmp_path)
    page = shared_browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/settings/display")
    radios = page.get_by_role("radiogroup", name="App icon").get_by_role("radio")
    radios.first.wait_for()
    assert radios.count() == 2
    assert radios.nth(0).get_attribute("data-icon") == "slate-bronze"
    assert radios.nth(1).get_attribute("data-icon") == "dark"
    assert radios.nth(0).get_attribute("aria-checked") == "true"
    radios.nth(1).click()
    assert page.wait_for_function(
        "() => document.querySelector('link[rel=\"apple-touch-icon\"]').href.includes("
        "'/icons/dark/apple-touch-icon.png')"
    )
    assert read_settings(app.state.settings_path) == {"app_icon": "dark"}
    manifest_url = page.locator('link[rel="manifest"]').get_attribute("href")
    manifest = page.evaluate(
        "async url => await (await fetch(url)).json()", manifest_url
    )
    assert manifest["icons"][0]["src"] == "/icons/dark/icon-192.png"


def test_settings_choice_groups_support_roving_keyboard_focus(
    browser_server, shared_browser_page, tmp_path
):
    origin, _ = start(browser_server, tmp_path)
    page = shared_browser_page
    page.goto(f"{origin}/settings/display")

    icons = page.get_by_role("radiogroup", name="App icon").get_by_role("radio")
    icons.first.wait_for()
    assert [icons.nth(i).get_attribute("tabindex") for i in range(icons.count())] == [
        "0",
        "-1",
    ]
    icons.first.focus()
    page.keyboard.press("ArrowRight")
    assert icons.nth(1).evaluate("element => document.activeElement === element")
    expect(icons.nth(1)).to_have_attribute("aria-checked", "true")

    themes = page.get_by_role("radiogroup", name="Theme").get_by_role("radio")
    selected_index = next(
        index
        for index in range(themes.count())
        if themes.nth(index).get_attribute("aria-checked") == "true"
    )
    next_index = (selected_index + 1) % themes.count()
    themes.nth(selected_index).focus()
    page.keyboard.press("ArrowRight")
    assert themes.nth(next_index).evaluate(
        "element => document.activeElement === element"
    )
    expect(themes.nth(next_index)).to_have_attribute("aria-checked", "true")


def test_settings_gutters_are_at_least_16px_in_light_and_dark(
    browser_server, shared_browser_page, tmp_path
):
    origin, _ = start(browser_server, tmp_path)
    page = shared_browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.route(
        "**/api/runner/config",
        lambda route: route.fulfill(
            json={
                "items": [
                    {"key": "types.standard.harness", "value": "codex-app-server"},
                    {"key": "types.standard.model", "value": "fixture-model"},
                    {"key": "types.standard.reasoning_effort", "value": "medium"},
                    {"key": "types.standard.fallback", "value": []},
                ],
                "choices": {
                    "codex-app-server": {
                        "harnesses": ["codex-app-server"],
                        "models": ["fixture-model"],
                        "reasoning_efforts": ["medium"],
                    }
                },
            }
        ),
    )
    for theme in ("light", "dark"):
        page.emulate_media(color_scheme=theme)
        page.goto(f"{origin}/settings")
        rows = page.locator("nav.settings-nav a[data-settings-row]")
        rows.first.wait_for()
        overview_row = rows.first.bounding_box()
        assert overview_row["x"] >= 16
        assert overview_row["x"] + overview_row["width"] <= 374
        hrefs = rows.evaluate_all(
            "links => links.map(link => link.getAttribute('href'))"
        )
        for href in hrefs:
            if href == "/roles":
                continue
            page.goto(f"{origin}{href}")
            header = page.locator(".chat-shell > .app-header")
            header.wait_for()
            rect = header.bounding_box()
            assert rect["x"] == 0
            assert rect["y"] == 0
            content = page.locator(".settings-content")
            assert (
                content.evaluate(
                    "element => element.getBoundingClientRect().x + "
                    "parseFloat(getComputedStyle(element).paddingLeft)"
                )
                == 16
            )
            assert (
                content.evaluate(
                    "element => element.getBoundingClientRect().right - "
                    "parseFloat(getComputedStyle(element).paddingRight)"
                )
                == 374
            )
            assert page.evaluate(
                "document.documentElement.scrollWidth <= "
                "document.documentElement.clientWidth"
            )
    page.goto(f"{origin}/settings/model-types")
    selects = page.locator(".settings-content select:visible")
    selects.first.wait_for()
    assert selects.count() >= 1, "model fallback editor should expose select controls"
    for index in range(selects.count()):
        select = selects.nth(index)
        assert (
            select.evaluate("element => getComputedStyle(element).fontSize") == "16px"
        )
        assert select.bounding_box()["height"] >= 44
    # The former multiline fallback editor is now structured select controls.
    assert page.locator(".settings-content textarea:visible").count() == 0


def _mock_runner_config(page, items):
    changes = []
    state = {
        "harness_enabled": False,
        "service": {"managed": True, "kind": "launchd", "installed": True},
        "restart_calls": [],
    }

    def config(route):
        if route.request.method == "GET":
            route.fulfill(json={"items": items})
            return
        payload = route.request.post_data_json
        changes.append(payload["changes"])
        if payload["changes"].get("codex_app_server.enabled") is False:
            route.fulfill(
                status=400,
                json={
                    "errors": {
                        "codex_app_server.enabled": (
                            "resulting config is invalid; review dependent settings"
                        )
                    }
                },
            )
            return
        for item in items:
            if item["key"] in payload["changes"]:
                item["value"] = payload["changes"][item["key"]]
        state["harness_enabled"] = payload["changes"].get(
            "codex_app_server.enabled", state["harness_enabled"]
        )
        route.fulfill(
            json={
                "items": items,
                "restart_required": any(
                    key.endswith(".enabled") for key in payload["changes"]
                ),
            }
        )

    def status(route):
        route.fulfill(
            json={
                "version": "test",
                "uptime_s": 10,
                "config_path": "test-config-path",
                "data_root": "test-data-root",
                "service": state["service"].copy(),
                "harnesses": [
                    {
                        "name": "codex-app-server",
                        "enabled": state["harness_enabled"],
                        "binary_found": True,
                        "login": "ready",
                        "hint": "Harness reports an active login.",
                    }
                ],
                "checklist": [
                    {
                        "id": "roles",
                        "done": False,
                        "hint": "Configure roles.",
                        "link": "/settings",
                    }
                ],
            }
        )

    def restart(route):
        state["restart_calls"].append(route.request.method)
        route.fulfill(status=202, json={"status": "restarting"})

    page.route("**/api/runner/config", config)
    page.route("**/api/runner/status", status)
    page.route("**/api/runner/restart", restart)
    return changes, state


def _assert_settings_layout(page):
    assert (
        page.locator(
            'input[type="password"], input[autocomplete*="password"], '
            'input[name*="token" i]'
        ).count()
        == 0
    )
    for width in (390, 1280):
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate(
            "document.documentElement.scrollWidth <= "
            "document.documentElement.clientWidth"
        )
        stripes = page.evaluate("""() => [...document.querySelectorAll('*')]
          .filter((el) => {
          const style = getComputedStyle(el);
          return parseFloat(style.borderLeftWidth) > 0 &&
            parseFloat(style.borderRightWidth) === 0 &&
            parseFloat(style.borderTopWidth) === 0 &&
            parseFloat(style.borderBottomWidth) === 0;
        }).length""")
        assert stripes == 0


def test_settings_config_validation_save_restart_and_harness_refusal(
    browser_server, shared_browser_page, tmp_path
):
    origin, _ = start(browser_server, tmp_path)
    page = shared_browser_page
    items = [
        {
            "key": "codex_app_server.enabled",
            "label": "Enabled",
            "hint": "Enable this runner harness.",
            "type": "boolean",
            "bounds": None,
            "value": False,
            "default": False,
            "restart_required": True,
            "group": "harnesses",
        },
        {
            "key": "limits.max_live_instances",
            "label": "Maximum live instances",
            "hint": "Limits concurrent runner sessions.",
            "type": "integer",
            "bounds": {"min": 1, "max": 4},
            "value": 2,
            "default": 2,
            "restart_required": False,
            "group": "limits",
        },
    ]
    changes, state = _mock_runner_config(page, items)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/settings/harnesses")
    enable = page.get_by_role("checkbox", name="Enable Codex")
    assert not enable.is_checked()
    enable.check()
    page.locator("#harnesses .saved").filter(has_text="Enabled saved.").wait_for()
    page.get_by_text("Harness reports an active login.").wait_for()
    assert changes == [{"codex_app_server.enabled": True}]
    assert (
        page.locator("#harnesses")
        .get_by_text("Restart the runner to apply this change.")
        .is_visible()
    )
    page.get_by_role("button", name="Restart runner").click()
    page.locator("#harnesses").get_by_role("status").filter(
        has_text="Runner restart requested."
    ).wait_for()
    page.goto(f"{origin}/settings/runner")
    advanced = page.locator("details.advanced")
    assert advanced.get_attribute("open") is None
    advanced.locator("summary").click()
    limit = page.get_by_role("spinbutton", name="Maximum live instances")
    limit.fill("5")
    advanced.get_by_role("button", name="Save").click()
    assert (
        page.locator('[role="alert"]')
        .filter(has_text="Must be at most 4.")
        .is_visible()
    )
    assert changes == [{"codex_app_server.enabled": True}]
    limit.fill("3")
    advanced.get_by_role("button", name="Save").click()
    page.get_by_role("status").filter(has_text="Saved").wait_for()
    assert changes[-1] == {"limits.max_live_instances": 3}
    assert page.get_by_text("Restart the runner to apply this change.").count() == 0
    page.goto(f"{origin}/settings/harnesses")
    page.get_by_role("checkbox", name="Enable Codex").uncheck()
    role_error = page.get_by_role("alert").filter(
        has_text="A role uses this harness; change it in Roles first."
    )
    role_error.wait_for()
    assert page.get_by_text("Restart the runner to apply this change.").count() == 0
    assert state["restart_calls"] == ["POST"]
    page.goto(f"{origin}/settings/runner")

    state["service"].update(managed=False, kind=None)
    advanced = page.locator("details.advanced")
    advanced.locator("summary").click()
    limit = page.get_by_role("spinbutton", name="Maximum live instances")
    limit.fill("4")
    advanced.get_by_role("button", name="Save").click()
    page.get_by_role("status").filter(has_text="Saved").wait_for()
    assert page.get_by_role("button", name="Restart runner").count() == 0
    assert (
        page.get_by_text(
            "Run varde-runner service start to restart under the service manager."
        ).count()
        == 0
    )


def test_settings_runner_host_controls_stay_config_only(
    browser_server, shared_browser_page, tmp_path
):
    origin, _ = start(browser_server, tmp_path)
    page = shared_browser_page
    items = [
        {
            "key": "runner.idle_process_timeout_s",
            "label": "Idle process timeout",
            "hint": "Seconds before an idle process is stopped.",
            "type": "integer",
            "bounds": {"min": 0, "max": 86400},
            "value": 600,
            "default": 600,
            "restart_required": False,
            "group": "runner",
        },
        {
            "key": "runner.require_user_pairing",
            "label": "Require browser pairing",
            "hint": "Require explicit browser pairing.",
            "type": "boolean",
            "bounds": None,
            "value": False,
            "default": False,
            "restart_required": False,
            "group": "runner",
        },
    ]
    changes, state = _mock_runner_config(page, items)
    state["service"].update(managed=False, kind=None)
    page.goto(f"{origin}/settings/runner")
    page.get_by_role("heading", name="Runner").first.wait_for()
    runner = page.get_by_role("region", name="Runner", exact=True)
    assert runner.get_by_role("spinbutton", name="Idle process timeout").count() == 0
    assert runner.get_by_role("checkbox", name="Require browser pairing").count() == 0
    assert changes == []
    assert page.get_by_text("Changes applied immediately.").is_visible()
    _assert_settings_layout(page)


def test_settings_shots(browser_server, shared_browser_page, tmp_path):
    import os

    shots = os.environ.get("VARDE_SETTINGS_SHOTS")
    if not shots:
        return
    origin, _ = start(browser_server, tmp_path)
    page = shared_browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/settings")
    page.get_by_role("heading", name="Settings").wait_for()
    for mode in ("light", "dark"):
        page.get_by_role("radio", name=mode.capitalize()).click()
        page.screenshot(
            path=f"{shots}/settings-390-{mode}.jpg", type="jpeg", quality=70
        )
    page.evaluate("localStorage.clear()")


def test_settings_controls_meet_touch_target_minimum(
    browser_server, shared_browser_page, tmp_path
):
    origin, _ = start(browser_server, tmp_path)
    page = shared_browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/settings/display")
    tile = page.get_by_role("radio", name="Light")
    tile.wait_for()
    assert tile.evaluate("e => e.getBoundingClientRect().height") >= 44
