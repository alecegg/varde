from __future__ import annotations

import argparse
import json
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parents[2]
APPROVED = (
    Path.home()
    / "source/agent-memory/projects/varde-py/working/reviews"
    / "2026-10-27-chat-first-prototype"
    / "APPROVED/index.html"
)
SCREENS = (
    "home",
    "empty-home",
    "menu",
    "thread-before",
    "thread-answered",
    "profile",
    "chips",
)
WIDTH, HEIGHT = 390, 844


def _load_prototype_data() -> dict[str, object]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(APPROVED.as_uri(), wait_until="load")
        data = page.evaluate("prototypeData")
        browser.close()
    return data


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _start_app() -> tuple[subprocess.Popen, str]:
    port = _port()
    process = subprocess.Popen(  # noqa: S603 - fixed npm preview command for a local build.
        [  # noqa: S607 - npm is resolved from PATH in this local developer tool.
            "npm",
            "run",
            "preview",
            "--",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--strictPort",
        ],
        cwd=ROOT / "runner/ui",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    origin = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Vite app server exited before becoming ready")
        try:
            urllib.request.urlopen(origin, timeout=1).close()
        except OSError:
            time.sleep(0.25)
        else:
            return process, origin
    process.terminate()
    raise RuntimeError("Vite app server did not start within 45 seconds")


def _mock_api(page, state: dict[str, object]) -> None:
    page.unroute_all(behavior="ignoreErrors")
    data = cast("dict[str, Any]", state["prototype_data"])
    agents = data["agents"]
    threads = data["threads"]
    notices = data["notices"]
    visible_notices = [notice for notice in notices if notice["type"] != "failed"]
    role_ids = {"manager": "manager-bot"}
    summaries = [
        {
            "role": role_ids.get(agent["id"], agent["id"]),
            "agent_id": agent["id"],
            "name": agent["name"],
            "hue": agent["color"],
            "initials": agent["initials"],
            "preview": agent["preview"],
            "state": "needs_you" if agent["state"] == "needs-you" else agent["state"],
            "queued": int(agent["state"] == "queued"),
            "needs_you": sum(
                bool(message.get("approval")) for message in threads[agent["id"]]
            ),
        }
        for agent in agents
    ]
    api_agents = []
    for agent in agents:
        requests = [
            {
                "request_id": f"{agent['id']}-{index}",
                "kind": "permission",
                "summary": message["approval"],
                "detail": "Review this request from the conversation.",
                "role_line": agent["name"],
            }
            for index, message in enumerate(threads[agent["id"]])
            if message.get("approval")
        ]
        api_agents.append(
            {
                "agent_id": agent["id"],
                "name": agent["name"],
                "harness": "codex",
                "role": role_ids.get(agent["id"], agent["id"]),
                "workspace": "varde-py",
                "lifecycle": agent["state"],
                "idle_status": None,
                "hue": agent["color"],
                "initials": agent["initials"],
                "capabilities": {"respond": True},
                "pending_requests": requests,
                "root_launched_by": "bot:manager"
                if agent["id"] == "manager"
                else "user",
            }
        )
    page.route(
        "**/api/home",
        lambda route: route.fulfill(json={"roles": summaries}),
    )
    page.route(
        "**/api/roles",
        lambda route: route.fulfill(json={"roles": state["role_config"]}),
    )
    page.route(
        "**/api/needs-you-count",
        lambda route: route.fulfill(
            json={
                "needs_you_count": sum(role["needs_you"] for role in summaries)
                + len(visible_notices)
            }
        ),
    )
    page.route("**/api/settings", lambda route: route.fulfill(json={"app_icon": ""}))
    page.route(
        "**/api/pairing",
        lambda route: route.fulfill(
            json={"enforced": False, "paired": True, "csrf": None}
        ),
    )
    notice_threads = [
        {
            "thread_id": f"notice:{notice['id']}",
            "plan_id": None,
            "sender": notice["title"],
            "title": notice["title"],
            "open_count": 1,
            "last_ts": "2026-10-27T08:00:00Z",
            "last_preview": notice["detail"],
            "decision_ids": [notice["id"]],
        }
        for notice in visible_notices
    ]
    notice_items = {
        notice["id"]: {
            "msg_id": notice["id"],
            "mailbox_open": True,
            "title": notice["detail"],
            "asked": notice["detail"],
            "body": notice["detail"],
            "kind": {
                "approval": "merge-ready",
                "question": "needs-user",
            }.get(notice["type"], notice["type"]),
            "type": notice["type"],
            "agent": notice["agent"],
            "agent_id": next(
                (a["id"] for a in agents if a["name"] == notice["agent"]), None
            ),
        }
        for notice in notices
    }
    page.route(
        "**/api/threads",
        lambda route: route.fulfill(
            json=[] if state.get("empty_home") else notice_threads
        ),
    )
    page.route(
        "**/api/mailbox?**",
        lambda route: route.fulfill(
            json={
                "items": [
                    notice_items[item_id]
                    for item_id in parse_qs(urlparse(route.request.url).query).get(
                        "ids", []
                    )
                    if item_id in notice_items
                ]
            }
        ),
    )
    page.route(
        "**/api/mailbox/*",
        lambda route: route.fulfill(
            json=notice_items.get(
                urlparse(route.request.url).path.rsplit("/", 1)[-1], {}
            )
        ),
    )
    page.route(
        "**/api/agents",
        lambda route: route.fulfill(json=[] if state.get("empty_home") else api_agents),
    )
    page.route(
        "**/api/agents/*/respond",
        lambda route: route.fulfill(json={"result": "ok"}),
    )
    page.route("**/api/degraded", lambda route: route.fulfill(json={"sources": []}))
    page.route(
        "**/api/queue/roles/**",
        lambda route: route.fulfill(
            json={
                "summary": {
                    "role": "manager-bot",
                    "state": "running",
                    "current": {"title": "Chat-first UI"},
                    "queued": 1,
                    "needs_you": 0,
                }
            }
        ),
    )
    page.route(
        "**/api/chat/stream**",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.route(
        "**/api/bot/audit**",
        lambda route: route.fulfill(
            json=[
                {
                    "id": index + 1,
                    "phase": "call",
                    "action": "launch",
                    "status": "allowed",
                    "agent_id": message.get("text", "")
                    .split(":", 1)[0]
                    .removeprefix("Delegated to "),
                    "plan_id": None,
                    "args_redacted": json.dumps({"role": "Builder"}),
                    "ts": f"2026-10-27T08:{index:02d}:00Z",
                }
                for index, message in enumerate(threads["manager"])
                if message.get("delegate")
            ]
        ),
    )
    page.route(
        "**/api/chat?**",
        lambda route: route.fulfill(
            json={
                "messages": [
                    {
                        "id": f"{state['thread_id']}-{index}",
                        "seq": index + 1,
                        "role": "user" if message.get("from") == "me" else "bot",
                        "text": message.get("text", message.get("approval", "")),
                        "created_at": f"2026-10-27T08:{index:02d}:00Z",
                        "kind": "message",
                        "change_seq": index + 1,
                    }
                    for index, message in enumerate(threads.get(state["thread_id"], []))
                    if not message.get("approval")
                ]
                + (
                    [
                        {
                            "id": "approval-answer",
                            "seq": len(threads.get(state["thread_id"], [])) + 1,
                            "role": "event",
                            "text": "APPROVED",
                            "created_at": "2026-10-27T08:10:00Z",
                            "kind": "answer",
                            "link": "request:manager-2",
                            "change_seq": len(threads.get(state["thread_id"], [])) + 1,
                        }
                    ]
                    if state.get("answered")
                    else []
                ),
                "latest_seq": len(threads.get(state["thread_id"], []))
                + int(bool(state.get("answered"))),
                "thread": {
                    "key": "main",
                    "kind": "main",
                    "label": None,
                    "state": "active",
                },
                "bot": {"state": "running", "context_pct": None, "generation": 0},
            }
        ),
    )
    page.route(
        "**/events",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.route(
        "**/api/identities",
        lambda route: route.fulfill(
            json={
                "identities": [
                    {
                        "id": agent["id"],
                        "name": agent["name"],
                        "label": agent["name"],
                        "role": role_ids.get(agent["id"], agent["id"]),
                        "description": agent["preview"],
                        "hue": agent["color"],
                        "initials": agent["initials"],
                        "count": 1,
                        "worst_state": agent["state"],
                        "instances": [],
                    }
                    for agent in agents
                ]
            }
        ),
    )


def _prepare(
    page, origin: str, theme: str, app: bool, state: dict[str, object], screen: str
) -> None:
    page.set_viewport_size({"width": WIDTH, "height": HEIGHT})
    page.emulate_media(color_scheme=theme, reduced_motion="reduce")
    if app:
        state["thread_id"] = "manager"
        state["empty_home"] = screen == "empty-home"
        _mock_api(page, state)
        page.add_init_script(
            """
            class StableEventSource {
              constructor() { setTimeout(() => this.onopen?.(), 0); }
              addEventListener() {}
              close() {}
            }
            window.EventSource = StableEventSource;
            """
        )
        path = {
            "home": "/",
            "empty-home": "/",
            "menu": "/thread/manager",
            "thread-before": "/thread/manager",
            "thread-answered": "/thread/manager",
            "profile": "/profile/builder",
            "chips": "/thread/manager",
        }[screen]
        state["thread_id"] = "builder" if screen == "profile" else "manager"
        state["answered"] = screen == "thread-answered"
        page.goto(f"{origin}{path}", wait_until="networkidle")
        page.evaluate(
            """theme => {
              document.documentElement.dataset.theme = theme;
              localStorage.setItem('varde:theme', theme);
            }""",
            theme,
        )
        page.reload(wait_until="networkidle")
        if screen == "menu":
            page.get_by_role("button", name="Open menu").click()
            page.get_by_role("dialog").wait_for()
            page.wait_for_timeout(300)
        if screen == "chips":
            page.evaluate(
                """() => {
                  const history = document.querySelector('.messages');
                  if (history) history.innerHTML = '';
                  document.querySelector('.pinned-content')?.remove();
                }"""
            )
        if screen.startswith("thread"):
            page.locator(".pinned-content > a.card").wait_for(timeout=5000)
    else:
        page.goto(APPROVED.as_uri() + "#/thread/manager", wait_until="load")
        page.reload(wait_until="load")
        page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
        if screen == "home":
            page.goto(APPROVED.as_uri() + "#/", wait_until="load")
        elif screen == "empty-home":
            page.goto(APPROVED.as_uri() + "#/", wait_until="load")
            page.evaluate(
                """() => {
                  document.querySelector('main').innerHTML =
                    '<section class=empty>' +
                    '<div style="font-size:32px;margin-bottom:12px">✓</div>' +
                    '<strong>All caught up</strong>' +
                    '<span>Nothing needs your attention right now.</span></section>';
                }"""
            )
        elif screen == "menu":
            page.locator("[data-menu]").click()
        elif screen == "profile":
            page.goto(APPROVED.as_uri() + "#/profile/builder", wait_until="load")
        elif screen.startswith("thread") or screen == "chips":
            if screen == "thread-answered":
                page.evaluate(
                    """() => {
                      const card = document.querySelector(
                        '.thread [data-answer-card="t-manager-2"]'
                      );
                      card.querySelector('.actions').outerHTML =
                        '<div class="meta"><span class="state">Approved</span></div>';
                    }"""
                )
            if screen == "chips":
                page.evaluate(
                    """() => {
                      const history = document.querySelector('.messages, .thread');
                      if (history) history.innerHTML = '';
                    }"""
                )
            if screen.startswith("thread"):
                queue_text = "Working on Chat-first UI, 1 in queue"
                page.evaluate(
                    """text => {
                  document.querySelectorAll('.queue-pin').forEach(pin => pin.remove());
                  const pin = document.createElement('a');
                  pin.className = 'queue-pin';
                  pin.setAttribute('aria-label', text);
                  const label = document.createElement('span');
                  label.textContent = text;
                  const arrow = document.createElement('span');
                  arrow.textContent = '›';
                  arrow.setAttribute('aria-hidden', 'true');
                  Object.assign(pin.style, {
                    position: 'fixed', zIndex: '4', bottom: '64px', left: '50%',
                    transform: 'translateX(-50%)', width: 'calc(100% - 32px)',
                    minHeight: '48px', padding: '8px 12px', display: 'flex',
                    alignItems: 'center', justifyContent: 'space-between', gap: '12px',
                    border: '1px solid var(--line)', borderRadius: '8px',
                    background: matchMedia('(prefers-color-scheme: dark)').matches
                      ? 'var(--panel)' : 'var(--soft)',
                    color: 'var(--text)', fontSize: '14px',
                    fontWeight: '700', textDecoration: 'none'
                  });
                  label.style.fontSize = '14px'; label.style.fontWeight = '700';
                  arrow.style.fontSize = '16px'; arrow.style.fontWeight = '700';
                  pin.append(label, arrow);
                  document.querySelector('main').append(pin);
                }""",
                    queue_text,
                )
    page.wait_for_timeout(150)


def _nonblank(path: Path, blank: bytes) -> None:
    assert path.read_bytes() != blank, f"{path} matches a blank page screenshot"


def create_tiles(destination: Path) -> None:
    if not APPROVED.is_file():
        raise FileNotFoundError(f"approved prototype not found: {APPROVED}")
    destination.mkdir(parents=True, exist_ok=True)
    process, origin = _start_app()
    state: dict[str, object] = {"prototype_data": _load_prototype_data()}
    state["role_config"] = {
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
    }
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
            blank_page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
            blank_page.set_content("<!doctype html><html><body></body></html>")
            blank = blank_page.screenshot()
            blank_page.close()
            for theme in ("light", "dark"):
                for screen in SCREENS:
                    for label, app in (("app", True), ("prototype", False)):
                        _prepare(page, origin, theme, app, state, screen)
                        output = destination / f"{screen}-{theme}-{label}.png"
                        page.screenshot(path=str(output), full_page=False)
                        _nonblank(output, blank)
            browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    tiles = list(destination.glob("*.png"))
    assert len(tiles) == 28, f"expected 28 tiles, found {len(tiles)}"
    print(
        json.dumps(
            {"count": len(tiles), "directory": str(destination), "max_width": WIDTH}
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture chat-first app and approved prototype tiles."
    )
    parser.add_argument("directory", type=Path)
    create_tiles(parser.parse_args().directory)


if __name__ == "__main__":
    main()
