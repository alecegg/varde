from __future__ import annotations

import argparse
import base64
import tempfile
from pathlib import Path
from typing import TypedDict

from chat_first_tiles import (
    APPROVED,
    HEIGHT,
    SCREENS,
    WIDTH,
    _load_prototype_data,
    _prepare,
    _start_app,
)
from playwright.sync_api import sync_playwright

# Selector pairs measured for each screen (app selector | approved prototype selector).
# | Screen/element | App selector | Prototype selector |
# | home/header | .shell-header strong | .top h1 |
# | home/list | .needs .cards | main .work-list |
# | home/card | .needs .cards > div > .card | main .work-list > .work-item |
# | home/title | .needs .work-item h2 | .work-item h2 |
# | home/detail and role | first and second .work-item p | matching p elements |
# | home/action | .needs .work-item .ui-button | .work-item .btn |
# | empty/header | .shell-header strong | .top h1 |
# | empty/main | main | main |
# | empty/state | .empty | .empty |
# | empty/title | .empty strong | .empty strong |
# | empty/detail | .empty p | .empty span |
# | menu/panel | .menu-panel | .panel |
# | menu/links | .menu-links | .links |
# | menu/first link | .menu-links a | .links a |
# | thread-before/header | .thread-header | .thread-head |
# | thread-before/avatar | .thread-header .avatar | .thread-head .avatar |
# | thread-before/message | .messages .message | .thread .bubble |
# | thread-before/delegation | .delegation-row | .thread .delegate |
# | thread-before/composer | .composer | .composer |
# | thread-before/input | .composer textarea | .composer input |
# | thread-answered/header | .thread-header | .thread-head |
# | thread-answered/state | .permission-status | .thread .state |
# | thread-answered/message | .messages .message | .thread .bubble |
# | thread-answered/composer | .composer | .composer |
# | profile/root | .profile-screen | .profile-screen |
# | profile/header | .profile-header | .profile |
# | profile/avatar | .profile-header .avatar | .profile .avatar |
# | profile/name | .profile-header h1 | .profile h2 |
# | profile/card | .profile-card | .config-card |
# | profile/row | .profile-row | .row |
# | chips | .avatars > .chip:nth-child(1..6) | matching prototype selectors |
# | chips/circle,label | each chip's .circle and .label | matching prototype selectors |
SCREEN_SELECTORS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "home": (
        ("header", ".shell-header strong", ".top h1"),
        ("avatar row", ".avatars", ".avatars"),
        ("hamburger icon", ".menu-button", ".top .icon"),
        ("needs-you list", ".needs .cards", "main .work-list"),
        ("card count", ".needs .cards > div > .card", "main .work-list > .work-item"),
        ("first card", ".needs .cards > div > .card", "main .work-list > .work-item"),
        ("title", ".needs .work-item h2", ".work-item h2"),
        (
            "description",
            ".needs .work-item p:nth-of-type(1)",
            ".work-item p:nth-of-type(1)",
        ),
        (
            "role line",
            ".needs .work-item p:nth-of-type(2)",
            ".work-item p:nth-of-type(2)",
        ),
        ("action", ".needs .work-item .ui-button", ".work-item .btn"),
        (
            "secondary deny button",
            ".needs .work-item .ui-button.danger",
            ".work-item .btn.danger",
        ),
    ),
    "empty-home": (
        ("header", ".shell-header strong", ".top h1"),
        ("main", "main", "main"),
        ("empty state", ".empty", ".empty"),
        ("empty icon", ".empty-icon", ".empty > div"),
        ("empty title", ".empty strong", ".empty strong"),
        ("empty detail", ".empty span", ".empty span"),
    ),
    "menu": (
        ("panel", ".menu-panel", ".panel"),
        ("heading", ".menu-heading", ".mhead"),
        ("links", ".menu-links", ".links"),
        ("needs-you link", ".menu-links a:nth-child(1)", ".links a:nth-child(1)"),
        ("conversations link", ".menu-links a:nth-child(2)", ".links a:nth-child(2)"),
        ("plans link", ".menu-links a:nth-child(3)", ".links a:nth-child(3)"),
        ("settings link", ".menu-links a:nth-child(4)", ".links a:nth-child(4)"),
        ("close button", ".menu-close", ".mhead .icon"),
    ),
    "thread-before": (
        ("thread header", ".thread-header", ".thread-head"),
        ("header avatar", ".thread-header .avatar", ".thread-head .avatar"),
        (
            "header status badge",
            ".thread-header .avatar::after",
            ".thread-head .avatar::after",
        ),
        ("thread name", ".thread-header h1", ".thread-head strong"),
        ("profile link", ".thread-header a", ".thread-head small"),
        (
            "bubble count",
            ".messages > .message, .messages .approval",
            ".thread > .bubble",
        ),
        (
            "bubble 1",
            ".messages > .message:nth-of-type(1)",
            ".thread > .bubble:nth-child(1)",
        ),
        (
            "bubble 2",
            ".messages > .message:nth-of-type(2)",
            ".thread > .bubble:nth-child(2)",
        ),
        ("approval card", ".messages .approval", ".thread [data-answer-card]"),
        (
            "approval Allow",
            ".messages .approval .primary",
            ".thread [data-answer-card] .primary",
        ),
        (
            "approval Deny",
            ".messages .approval .danger",
            ".thread [data-answer-card] .danger",
        ),
        ("delegation", ".delegation-row", ".thread .delegate"),
        ("pinned queue card", ".pinned-content > a.card", ".queue-pin"),
        ("composer", ".composer", ".composer"),
        ("composer input", ".composer textarea", ".composer input"),
        ("composer send", ".composer .send", ".composer .send"),
    ),
    "thread-answered": (
        ("thread header", ".thread-header", ".thread-head"),
        ("header avatar", ".thread-header .avatar", ".thread-head .avatar"),
        (
            "header status badge",
            ".thread-header .avatar::after",
            ".thread-head .avatar::after",
        ),
        ("thread name", ".thread-header h1", ".thread-head strong"),
        ("profile link", ".thread-header a", ".thread-head small"),
        (
            "bubble count",
            ".messages > .message, .messages .approval",
            ".thread > .bubble",
        ),
        (
            "bubble 1",
            ".messages > .message:nth-of-type(1)",
            ".thread > .bubble:nth-child(1)",
        ),
        (
            "bubble 2",
            ".messages > .message:nth-of-type(2)",
            ".thread > .bubble:nth-child(2)",
        ),
        (
            "approval state",
            ".messages .approval .state",
            ".thread [data-answer-card] .state",
        ),
        ("approval card", ".messages .approval", ".thread [data-answer-card]"),
        ("delegation", ".delegation-row", ".thread .delegate"),
        ("pinned queue card", ".pinned-content > a.card", ".queue-pin"),
        ("composer", ".composer", ".composer"),
        ("composer input", ".composer textarea", ".composer input"),
        ("composer send", ".composer .send", ".composer .send"),
    ),
    "profile": (
        ("profile", ".profile-screen", ".profile-screen"),
        ("back button", ".profile-back", ".profile-back"),
        ("profile header", ".profile", ".profile"),
        ("avatar", ".profile .avatar", ".profile .avatar"),
        ("name", ".profile h2", ".profile h2"),
        ("state pill", ".profile .state", ".profile .state"),
        ("config card", ".config-card", ".config-card"),
        (
            "config row",
            ".config-card .row:nth-child(1)",
            ".config-card .row:nth-child(1)",
        ),
        (
            "config row 2",
            ".config-card .row:nth-child(2)",
            ".config-card .row:nth-child(2)",
        ),
        (
            "config row 3",
            ".config-card .row:nth-child(3)",
            ".config-card .row:nth-child(3)",
        ),
        (
            "config row 4",
            ".config-card .row:nth-child(4)",
            ".config-card .row:nth-child(4)",
        ),
        ("back to conversation", ".profile-return", ".profile-return"),
    ),
    "chips": tuple(
        (
            f"chip {index} position",
            f".avatars > .chip:nth-child({index})",
            f".avatars > .chip:nth-child({index})",
        )
        for index in range(1, 7)
    )
    + tuple(
        (
            f"chip {index} status badge",
            f".avatars > .chip:nth-child({index}) .circle.{state}::after",
            f".avatars > .chip:nth-child({index}) .circle.{state}::after",
        )
        for index, state in (
            (2, "running"),
            (3, "running"),
            (4, "queued"),
            (5, "needs-you"),
        )
    )
    + tuple(
        (
            f"chip {index} {part}",
            f".avatars > .chip:nth-child({index}) .{part}",
            f".avatars > .chip:nth-child({index}) .{part}",
        )
        for index in range(1, 7)
        for part in ("circle", "label")
    )
    + (("chip count", ".avatars > .chip", ".avatars > .chip"),),
}
STYLES = (
    "fontSize",
    "fontWeight",
    "fontFamily",
    "lineHeight",
    "letterSpacing",
    "color",
    "backgroundColor",
    "backgroundImage",
    "borderRadius",
    "borderColor",
    "borderWidth",
    "borderStyle",
    "resize",
)
TOLERANCE = 1.0


def _measure(page, selector: str) -> dict[str, object] | None:
    is_after = selector.endswith("::after")
    element_selector = selector.removesuffix("::after") if is_after else selector
    locators = page.locator(element_selector)
    count = locators.count()
    if count == 0:
        return None
    locator = locators.first
    return locator.evaluate(
        """(node, options) => {
      const {isAfter, count} = options;
      const rect = node.getBoundingClientRect();
      const css = isAfter ? getComputedStyle(node, '::after') : getComputedStyle(node);
      let x = rect.x, y = rect.y, width = rect.width, height = rect.height;
      if (isAfter) {
        width = parseFloat(css.width); height = parseFloat(css.height);
        x += rect.width - width - parseFloat(css.right || 0);
        y += rect.height - height - parseFloat(css.bottom || 0);
      }
      return {x, y, width, height,
        fontSize: css.fontSize, fontWeight: css.fontWeight, color: css.color,
        fontFamily: css.fontFamily, lineHeight: css.lineHeight,
        letterSpacing: css.letterSpacing,
        backgroundColor: css.backgroundColor, backgroundImage: css.backgroundImage,
        borderRadius: css.borderRadius, borderWidth: css.borderWidth,
        borderColor: css.borderColor,
        borderStyle: css.borderStyle, resize: css.resize,
        right: css.right, bottom: css.bottom,
        textContent: isAfter ? '' : (node.innerText || node.textContent)
          .replace(/\\s+/g, ' ').trim(),
        placeholder: node.getAttribute('placeholder') || '', count};
    }""",
        {"isAfter": is_after, "count": count},
    )


def _capture(page, directory: Path, screen: str, theme: str, side: str) -> bytes:
    image = page.screenshot(
        path=str(directory / f"{screen}-{theme}-{side}-full.png"), full_page=True
    )
    # Re-display the full-resolution capture at natural density and crop tiles.
    tile_page = page.context.browser.new_page(
        viewport={"width": WIDTH, "height": 540}, device_scale_factor=1
    )
    uri = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
    tile_page.set_content(
        f"<style>html,body{{margin:0;padding:0}}"
        f'img{{display:block;width:{WIDTH}px;height:auto}}</style><img src="{uri}">'
    )
    size = tile_page.locator("img").evaluate(
        "img => ({width: img.naturalWidth, height: img.naturalHeight})"
    )
    tile_page.set_viewport_size({"width": size["width"], "height": size["height"]})
    for index, top in enumerate(range(0, size["height"], 540), start=1):
        height = min(540, size["height"] - top)
        tile_page.screenshot(
            path=str(directory / f"{screen}-{theme}-{side}-tile-{index}.png"),
            clip={"x": 0, "y": top, "width": size["width"], "height": height},
        )
    tile_page.close()
    return image


class PixelDiff(TypedDict):
    width: int
    height: int
    appHeight: int
    prototypeHeight: int
    percent: float
    bbox: list[int] | None
    worstRegion: list[int] | None
    png: str


def _pixel_diff(browser, app_png: bytes, proto_png: bytes) -> PixelDiff:
    page = browser.new_page()
    result = page.evaluate(
        """async ({app, prototype}) => {
          const load = value => new Promise((resolve, reject) => {
            const image = new Image();
            image.onload = () => resolve(image);
            image.onerror = reject;
            image.src = `data:image/png;base64,${value}`;
          });
          const [left, right] = await Promise.all([load(app), load(prototype)]);
          const width = Math.max(left.naturalWidth, right.naturalWidth);
          const height = Math.max(left.naturalHeight, right.naturalHeight);
          const regionSize = 64;
          const regionColumns = Math.ceil(width / regionSize);
          const regions = new Array(
            regionColumns * Math.ceil(height / regionSize)
          ).fill(0);
          const canvas = document.createElement('canvas');
          canvas.width = width; canvas.height = height;
          const context = canvas.getContext('2d', {willReadFrequently: true});
          const draw = image => {
            const layer = document.createElement('canvas');
            layer.width = width; layer.height = height;
            const layerContext = layer.getContext('2d');
            layerContext.drawImage(image, 0, 0);
            return layerContext.getImageData(0, 0, width, height).data;
          };
          const a = draw(left), b = draw(right);
          const out = context.createImageData(width, height);
          let changed = 0, minX = width, minY = height, maxX = -1, maxY = -1;
          for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
            const i = (y * width + x) * 4;
            const outside = x >= left.naturalWidth || y >= left.naturalHeight
              || x >= right.naturalWidth || y >= right.naturalHeight;
            const delta = outside ? 255 : Math.max(
              Math.abs(a[i] - b[i]), Math.abs(a[i + 1] - b[i + 1]),
              Math.abs(a[i + 2] - b[i + 2]), Math.abs(a[i + 3] - b[i + 3])
            );
            if (delta > 8) {
              changed++; minX = Math.min(minX, x); minY = Math.min(minY, y);
              maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
              regions[Math.floor(y / regionSize) * regionColumns
                + Math.floor(x / regionSize)]++;
              out.data[i] = 255; out.data[i + 1] = 0; out.data[i + 2] = 180;
              out.data[i + 3] = 255;
            } else {
              const gray = outside ? 255 : Math.round((a[i] + a[i + 1] + a[i + 2]) / 3);
              out.data[i] = gray; out.data[i + 1] = gray;
              out.data[i + 2] = gray; out.data[i + 3] = 255;
            }
          }
          const worstIndex = regions.indexOf(Math.max(...regions));
          const worstX = worstIndex % regionColumns * regionSize;
          const worstY = Math.floor(worstIndex / regionColumns) * regionSize;
          context.putImageData(out, 0, 0);
          return {
            width, height, appHeight: left.naturalHeight,
            prototypeHeight: right.naturalHeight,
            percent: changed / (width * height) * 100,
            bbox: maxX < 0 ? null : [minX, minY, maxX + 1, maxY + 1],
            worstRegion: changed === 0 ? null : [
              worstX, worstY, Math.min(width, worstX + regionSize),
              Math.min(height, worstY + regionSize)
            ],
            png: canvas.toDataURL('image/png').split(',')[1]
          };
        }""",
        {
            "app": base64.b64encode(app_png).decode("ascii"),
            "prototype": base64.b64encode(proto_png).decode("ascii"),
        },
    )
    page.close()
    return result


def _thread_order(page) -> dict[str, object]:
    return page.evaluate("""() => {
      const messages = document.querySelector('.messages, .thread');
      const approval = messages?.querySelector(
        '[data-testid="inline-approval"], [data-answer-card]'
      );
      const pinned = document.querySelector('.pinned-content > a.card, .queue-pin');
      const composer = document.querySelector('.composer');
      if (!messages || !approval || !pinned || !composer) return {complete: false};
      const follows = (first, second) => Boolean(
        first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING
      );
      return {
        complete: true,
        approvalInHistory: messages.contains(approval),
        pinAfterHistory: follows(messages, pinned),
        pinBeforeComposer: follows(pinned, composer),
        pinAboveComposer: pinned.getBoundingClientRect().bottom
          <= composer.getBoundingClientRect().top + 1,
      };
    }""")


def _menu_pin_is_hidden(page) -> bool:
    return page.evaluate("""() => {
      const pin = document.querySelector('.pinned-content > a.card, .queue-pin');
      if (!pin) return true;
      const rect = pin.getBoundingClientRect();
      let node = pin;
      while (node) {
        const style = getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden') return true;
        node = node.parentElement;
      }
      return rect.width === 0 || rect.height === 0;
    }""")


def _verify_allow_flow(page) -> None:
    card = page.locator('.messages [data-testid="inline-approval"]')
    card.get_by_role("button", name="Allow").click()
    page.wait_for_function(
        "document.querySelector('.messages [data-testid=inline-approval]')?."
        "dataset.answer === 'approved'"
    )
    if card.get_attribute("data-answer") != "approved":
        raise AssertionError("Allow did not resolve inline approval to approved")


def _menu_pin_failures(
    theme: str, app_page, proto_page
) -> list[tuple[str, str, str, str]]:
    failures = []
    for side, page in (("app", app_page), ("prototype", proto_page)):
        if not _menu_pin_is_hidden(page):
            detail = f"{side} queue pin remains visible through menu scrim"
            failures.append((theme, "menu", "hidden queue pin", detail))
            print(f"{theme:5} menu             hidden queue pin   DIFF {detail}")
    return failures


def compare_screen(
    screen: str, theme: str, app_page, proto_page
) -> list[tuple[str, str, str, str]]:
    app_rows = []
    proto_rows = []
    for name, app_selector, proto_selector in SCREEN_SELECTORS[screen]:
        app_rows.append((name, app_selector, _measure(app_page, app_selector)))
        proto_rows.append((name, proto_selector, _measure(proto_page, proto_selector)))
    failures = []
    print("theme screen           element            result boxΔ(x,y,w,h) style diff")
    for (name, app_selector, app_metric), (_, proto_selector, proto_metric) in zip(
        app_rows, proto_rows, strict=True
    ):
        if app_metric is None or proto_metric is None:
            failures.append((theme, screen, name, "missing selector"))
            print(
                f"{theme:5} {screen:16} {name:18} MISSING "
                f"app={app_selector if app_metric is None else '-'} "
                f"prototype={proto_selector if proto_metric is None else '-'}"
            )
            continue
        deltas = [
            abs(float(app_metric[key]) - float(proto_metric[key]))
            for key in ("x", "y", "width", "height")
        ]
        strict_font_styles = {"fontFamily", "lineHeight", "letterSpacing"}
        style_keys = (
            STYLES
            if screen in {"menu", "profile"}
            else tuple(key for key in STYLES if key not in strict_font_styles)
        )
        style_diff = [key for key in style_keys if app_metric[key] != proto_metric[key]]
        if app_metric["borderWidth"] in ("0px", "0px 0px 0px 0px"):
            style_diff = [key for key in style_diff if key != "borderColor"]
        if name.endswith("status badge"):
            if (app_metric["width"], app_metric["height"]) != (14, 14):
                style_diff.append("dotSize")
            if app_metric["borderWidth"] != "2px":
                style_diff.append("dotRing")
            style_diff.extend(
                key
                for key in ("borderWidth", "borderColor", "right", "bottom")
                if app_metric[key] != proto_metric[key]
            )
        if name == "composer input" and app_metric["resize"] != "none":
            style_diff.append("resize")
        if name == "composer send" and (
            app_metric["width"] != 48 or app_metric["height"] != 48
        ):
            style_diff.append("sendSize")
        compare_text = name.endswith(
            ("circle", "label", "avatar", "bubble", "Allow", "Deny", "send")
        ) or name in {
            "hamburger icon",
            "thread name",
            "profile link",
            "approval card",
            "pinned queue card",
            "composer input",
            "approval state",
            "empty icon",
            "empty title",
            "empty detail",
            "state pill",
            "config row",
            "config row 2",
            "config row 3",
            "config row 4",
            "back to conversation",
        }
        text_diff = (
            compare_text and app_metric["textContent"] != proto_metric["textContent"]
        )
        if name == "composer input":
            text_diff = (
                text_diff or app_metric["placeholder"] != proto_metric["placeholder"]
            )
        count_diff = app_metric["count"] != proto_metric["count"]
        passed = (
            max(deltas, default=0) <= TOLERANCE
            and not style_diff
            and not text_diff
            and not count_diff
        )
        style_values = (
            ",".join(
                f"{key}={app_metric[key]}|{proto_metric[key]}" for key in style_diff
            )
            or "same"
        )
        if text_diff:
            style_values += (
                f" text={app_metric['textContent']!r}|{proto_metric['textContent']!r}"
            )
        if (
            name == "composer input"
            and app_metric["placeholder"] != proto_metric["placeholder"]
        ):
            style_values += (
                f" placeholder={app_metric['placeholder']!r}|"
                f"{proto_metric['placeholder']!r}"
            )
        if count_diff:
            style_values += f" count={app_metric['count']}|{proto_metric['count']}"
        if not passed:
            delta_text = ",".join(f"{delta:.1f}" for delta in deltas)
            detail = f"box Δ={delta_text} styles={style_values}"
            failures.append((theme, screen, name, detail))
        print(
            f"{theme:5} {screen:16} {name:18} "
            f"{'OK' if passed else 'DIFF'} "
            f"{','.join(f'{delta:.1f}' for delta in deltas)} {style_values}"
        )
    if screen.startswith("thread"):
        for side, page in (("app", app_page), ("prototype", proto_page)):
            order = _thread_order(page)
            passed = order.get("complete") and all(
                order.get(key)
                for key in (
                    "approvalInHistory",
                    "pinAfterHistory",
                    "pinBeforeComposer",
                    "pinAboveComposer",
                )
            )
            if not passed:
                detail = f"{side} approval/pin/composer order: {order}"
                failures.append((theme, screen, "pinned card order", detail))
                print(f"{theme:5} {screen:16} pinned card order   DIFF {detail}")
    if screen == "menu":
        failures.extend(_menu_pin_failures(theme, app_page, proto_page))
    return failures


def run(selected: str, destination: Path) -> int:
    if not APPROVED.is_file():
        raise FileNotFoundError(f"approved prototype not found: {APPROVED}")
    destination.mkdir(parents=True, exist_ok=True)
    process, origin = _start_app()
    state: dict[str, object] = {
        "prototype_data": _load_prototype_data(),
        "role_config": {
            "manager-bot": {
                "harness": "codex-app-server",
                "model": "gpt-6",
                "reasoning_effort": "high",
            },
            "builder": {
                "harness": "codex-app-server",
                "model": "GPT-6",
                "reasoning_effort": "standard",
            },
        },
    }
    failures = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            app_page = browser.new_page(
                viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1
            )
            proto_page = browser.new_page(
                viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1
            )
            for theme in ("light", "dark"):
                for screen in SCREENS if selected == "all" else (selected,):
                    for page, app in ((app_page, True), (proto_page, False)):
                        _prepare(page, origin, theme, app, state, screen)
                    app_png = _capture(app_page, destination, screen, theme, "app")
                    proto_png = _capture(
                        proto_page, destination, screen, theme, "prototype"
                    )
                    pixel_result = _pixel_diff(browser, app_png, proto_png)
                    diff_path = destination / f"{screen}-{theme}-diff.png"
                    diff_path.write_bytes(base64.b64decode(pixel_result["png"]))
                    dimensions_match = (
                        pixel_result["appHeight"] == pixel_result["prototypeHeight"]
                    )
                    pixel_passed = dimensions_match and pixel_result["percent"] <= 0.5
                    print(
                        f"{theme:5} {screen:16} full-page height "
                        f"app={pixel_result['appHeight']} "
                        f"prototype={pixel_result['prototypeHeight']} "
                        f"{'OK' if dimensions_match else 'DIFF'}"
                    )
                    print(
                        f"{theme:5} {screen:16} pixel diff "
                        f"{pixel_result['percent']:.3f}% "
                        f"worst region={pixel_result['worstRegion']} "
                        f"image={diff_path} "
                        f"{'OK' if pixel_passed else 'DIFF'}"
                    )
                    if not pixel_passed:
                        failures.append(
                            (
                                theme,
                                screen,
                                "full-page pixel diff",
                                (
                                    f"{pixel_result['percent']:.3f}% "
                                    f"bbox={pixel_result['worstRegion']} "
                                    f"height={pixel_result['appHeight']}|"
                                    f"{pixel_result['prototypeHeight']}"
                                ),
                            )
                        )
                    failures.extend(compare_screen(screen, theme, app_page, proto_page))
                    if screen == "thread-before":
                        _verify_allow_flow(app_page)
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=10)
    print(f"\n{len(failures)} comparison mismatches; artifacts: {destination}")
    return int(bool(failures))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare chat-first app rendering with the approved prototype."
    )
    parser.add_argument("--screen", choices=(*SCREENS, "all"), default="all")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(tempfile.gettempdir()) / "chat-first-compare",
    )
    args = parser.parse_args()
    raise SystemExit(run(args.screen, args.output))


if __name__ == "__main__":
    main()
