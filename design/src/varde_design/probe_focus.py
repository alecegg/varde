"""Keyboard focus walk: Tab through the page and measure each focus indicator.

Plain-data measurement only; `render_rules.check_focus` decides. For each stop
the pixels around the element are compared focused against blurred inside the
page, and the most frequent changed (focused, blurred) colour pairs are kept.
"""

from __future__ import annotations

import base64
import contextlib
from typing import Any

MAX_FOCUS_STOPS = 30
CLIP_PAD_PX = 8

RESET_SCRIPT = """() => {
  if (document.activeElement) document.activeElement.blur();
  window.__vardeSeen = new WeakSet();
  window.scrollTo(0, 0);
}"""

STOP_SCRIPT = """() => {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  const repeat = window.__vardeSeen.has(el);
  window.__vardeSeen.add(el);
  const r = el.getBoundingClientRect();
  return {
    selector: window.__vardeSelector
      ? window.__vardeSelector(el) : el.tagName.toLowerCase(),
    tag: el.tagName.toLowerCase(), repeat,
    rect: {x: r.x, y: r.y, width: r.width, height: r.height},
  };
}"""

DIFF_SCRIPT = """async ([a, b]) => {
  const load = (s) => new Promise((ok, no) => {
    const i = new Image();
    i.onload = () => ok(i);
    i.onerror = no;
    i.src = 'data:image/png;base64,' + s;
  });
  const [x, y] = await Promise.all([load(a), load(b)]);
  const w = x.width, h = x.height;
  const cv = document.createElement('canvas');
  cv.width = w; cv.height = h;
  const cx = cv.getContext('2d', {willReadFrequently: true});
  cx.drawImage(x, 0, 0);
  const A = cx.getImageData(0, 0, w, h).data;
  cx.clearRect(0, 0, w, h);
  cx.drawImage(y, 0, 0);
  const B = cx.getImageData(0, 0, w, h).data;
  const pairs = new Map();
  for (let i = 0; i < A.length; i += 4) {
    const d = Math.abs(A[i] - B[i]) + Math.abs(A[i + 1] - B[i + 1])
      + Math.abs(A[i + 2] - B[i + 2]);
    if (d <= 24) continue;
    const key = [A[i], A[i + 1], A[i + 2]].join(', ') + '|'
      + [B[i], B[i + 1], B[i + 2]].join(', ');
    pairs.set(key, (pairs.get(key) || 0) + 1);
  }
  const rgba = (t) => 'rgba(' + t + ', 1.000)';
  return Array.from(pairs.entries())
    .sort((p, q) => q[1] - p[1] || (p[0] < q[0] ? -1 : 1))
    .slice(0, 12)
    .map(([key, count]) => {
      const [fg, bg] = key.split('|');
      return {fg: rgba(fg), bg: rgba(bg), count};
    });
}"""


def _clip(rect: dict[str, float], viewport: dict[str, int]) -> dict[str, float] | None:
    """The padded element box clamped to the viewport, or None when empty."""
    left = max(0.0, rect["x"] - CLIP_PAD_PX)
    top = max(0.0, rect["y"] - CLIP_PAD_PX)
    right = min(float(viewport["width"]), rect["x"] + rect["width"] + CLIP_PAD_PX)
    bottom = min(float(viewport["height"]), rect["y"] + rect["height"] + CLIP_PAD_PX)
    if right - left < 1 or bottom - top < 1:
        return None
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _changes(page: Any, clip: dict[str, float]) -> list[dict[str, Any]] | None:
    """Changed colour pairs between the focused and blurred element, or None."""
    focused = page.screenshot(clip=clip, animations="disabled")
    page.evaluate("document.activeElement.blur()")
    blurred = page.screenshot(clip=clip, animations="disabled")
    pair = [base64.b64encode(shot).decode("ascii") for shot in (focused, blurred)]
    # A page security policy can block the in-page image decode: unknown, not a defect.
    with contextlib.suppress(Exception):
        return page.evaluate(DIFF_SCRIPT, pair)
    return None


def walk_focus(page: Any) -> dict[str, Any]:
    """Tab through the page; a stop is {selector, tag, changes}."""
    page.evaluate(RESET_SCRIPT)
    viewport = page.viewport_size
    stops: list[dict[str, Any]] = []
    for _ in range(MAX_FOCUS_STOPS):
        page.keyboard.press("Tab")
        stop = page.evaluate(STOP_SCRIPT)
        if stop is None or stop["repeat"]:
            return {"stops": stops, "capped": False}
        clip = _clip(stop["rect"], viewport)
        changes = None if clip is None else _changes(page, clip)
        stops.append(
            {"selector": stop["selector"], "tag": stop["tag"], "changes": changes}
        )
    return {"stops": stops, "capped": True}
