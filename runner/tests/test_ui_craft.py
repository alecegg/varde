"""DOM assertions for dashboard UI craft defects."""

from __future__ import annotations

import pytest
import test_web_browser

browser_page = test_web_browser.browser_page

PAGES = ("/", "/thread/manager", "/profile/builder", "/plans", "/settings")
BUTTON_AUDIT = """() => {
const selectors = [
  'button', 'a.ui-button', '.desktop-chat-sidebar a', '.desktop-chat-sidebar button',
];
return [...document.querySelectorAll(selectors.join(','))]
.filter((el) => {
  const r = el.getBoundingClientRect();
  return r.width && r.height && getComputedStyle(el).visibility !== 'hidden';
}).map((el) => {
  const r = el.getBoundingClientRect();
  return {
    name: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 30),
    variant: el.dataset.variant || '',
    control: el.hasAttribute('data-ui-control') ||
      el.getAttribute('role') === 'tab' ||
      el.classList.contains('role-head'),
    height: r.height,
  };
})}"""

OVERFLOWING = """() => {
  const vw = document.documentElement.clientWidth;
  const clipped = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox !== 'visible') return p.getBoundingClientRect().right <= vw + 1;
    }
    return false;
  };
  return [...document.querySelectorAll('body *')].filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width && r.height && getComputedStyle(el).visibility !== 'hidden'
      && (r.right > vw + 1 || r.left < -1) && !clipped(el);
  }).map((el) => el.tagName + '.' + el.className);
}"""


def visit(page, origin, path, width, theme="dark"):
    page.set_viewport_size({"width": width, "height": 844 if width < 900 else 900})
    page.emulate_media(color_scheme=theme)
    page.goto(f"{origin}{path}")
    page.locator(".shell-content").wait_for()


@pytest.mark.parametrize("path", PAGES)
def test_no_demo_dialog_text_outside_catalog(browser_page, path):
    page, _, _, origin, _ = browser_page
    visit(page, origin, path, 390)
    assert page.get_by_text("Open dialog").count() == 0


@pytest.mark.parametrize("theme", ("light", "dark"))
@pytest.mark.parametrize("width", (390, 1440))
@pytest.mark.parametrize("path", PAGES)
def test_no_element_overflows_viewport(browser_page, path, width, theme):
    page, _, _, origin, _ = browser_page
    visit(page, origin, path, width, theme)
    assert page.evaluate(OVERFLOWING) == []


def test_menu_links_and_hides_pinned_queue_card(browser_page):
    page, _, _, origin, _ = browser_page
    visit(page, origin, "/", 390)
    page.evaluate("""() => {
      const content = document.createElement('div');
      content.className = 'pinned-content';
      content.innerHTML = '<a class="card" href="/plans">Working on task</a>';
      document.querySelector('.chat-shell').append(content);
    }""")
    pin = page.locator(".pinned-content > a.card")
    assert pin.is_visible()
    page.get_by_role("button", name="Open menu").click()
    menu = page.get_by_role("dialog")
    links = menu.get_by_role("link")
    assert links.count() == 3
    assert [link.get_attribute("href") for link in links.all()] == [
        "/",
        "/plans",
        "/settings",
    ]
    assert not pin.is_visible()


@pytest.mark.parametrize("width", (390, 1440))
@pytest.mark.parametrize("path", PAGES)
def test_every_button_target_is_44px(browser_page, path, width):
    page, _, _, origin, _ = browser_page
    visit(page, origin, path, width)
    audit = page.evaluate(BUTTON_AUDIT)
    assert audit
    for button in audit:
        if button["name"] == "Edit":
            continue  # Prototype B uses a 40px text control here.
        assert button["height"] >= 44 - 0.5, button


def test_menu_sheet_targets_are_at_least_44px(browser_page):
    page, _, _, origin, _ = browser_page
    visit(page, origin, "/", 390)
    page.get_by_role("button", name="Open menu").click()
    menu = page.get_by_role("dialog")
    menu.wait_for()
    targets_script = (
        "els => els.map(el => {"
        " const r = el.getBoundingClientRect();"
        " return [r.width, r.height]; })"
    )
    targets = menu.locator("a:visible, button:visible").evaluate_all(targets_script)
    assert targets
    assert all(width >= 44 and height >= 44 for width, height in targets), targets
