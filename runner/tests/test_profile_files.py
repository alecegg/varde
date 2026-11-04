from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
import test_web_browser
from starlette.applications import Starlette
from varde_runner.web.app import UI_DIR
from varde_runner.web.identities_route import create_identities_routes

browser_page = test_web_browser.browser_page

pytest_plugins = ["test_agents_page_browser"]


def _request(app, method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else b""

    async def dispatch():
        messages = []
        consumed = False

        async def receive():
            nonlocal consumed
            if consumed:
                return {"type": "http.disconnect"}
            consumed = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [(b"host", b"localhost")],
                "client": ("127.0.0.1", 1),
                "server": ("localhost", 80),
            },
            receive,
            send,
        )
        start = next(item for item in messages if item["type"] == "http.response.start")
        response_body = b"".join(
            item.get("body", b"")
            for item in messages
            if item["type"] == "http.response.body"
        )
        return start["status"], json.loads(response_body)

    return asyncio.run(dispatch())


def test_api_reads_invalid_profile_as_defaults_and_repairs_only_its_file(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    directory = tmp_path / "identities"
    directory.mkdir()
    builder = directory / "builder.toml"
    reviewer = directory / "reviewer.toml"
    builder.write_text("name = [invalid\n")
    reviewer.write_bytes(
        b'name = "Review Crew"\nlabel = "review"\n'
        b'description = "Reviews changes."\nrole = "reviewer"\n'
    )
    reviewer_before = reviewer.read_bytes()
    supervisor = SimpleNamespace(data_dir=tmp_path / "state")

    import varde_runner.web.identities_route as module

    async def no_agent_rows(_supervisor):
        return []

    monkeypatch.setattr(module, "_agent_rows", no_agent_rows)
    app = Starlette(routes=create_identities_routes(lambda: supervisor))
    status, body = _request(app, "GET", "/api/identities")
    builder_identity = next(
        item for item in body["identities"] if item["id"] == "builder"
    )
    assert status == 200
    assert builder_identity["error"]
    assert builder_identity["name"] == "Builder"
    assert builder_identity["description"] == "Implements one task at a time."

    status, saved = _request(
        app,
        "PUT",
        "/api/identities/builder",
        {
            "name": "Build Team",
            "label": "builders",
            "description": "Builds requested work.",
        },
    )
    assert status == 200 and saved["name"] == "Build Team"
    assert 'name = "Build Team"' in builder.read_text()
    assert 'role = "builder"' in builder.read_text()
    assert reviewer.read_bytes() == reviewer_before


@pytest.mark.skipif(
    not (UI_DIR / "index.html").is_file(), reason="runner UI is not built"
)
def test_invalid_profile_is_read_only_and_opens_with_defaults_in_chat_profile(
    browser_page, tmp_path
):
    page, _, _, _, _ = browser_page
    directory = tmp_path / "identities"
    directory.mkdir()
    builder = directory / "builder.toml"
    reviewer = directory / "reviewer.toml"
    builder.write_text("name = [invalid\n")
    reviewer.write_bytes(b'custom = "leave byte-for-byte"\n')
    reviewer_before = reviewer.read_bytes()
    profile = {
        "name": "Builder",
        "label": "builder",
        "description": "Implements one task at a time.",
    }

    def roster(route):
        route.fulfill(
            json={
                "identities": [
                    {
                        "id": "builder",
                        **profile,
                        "role": "builder",
                        "kind": "role",
                        "count": 1,
                        "worst_state": "idle",
                        "instances": None,
                        "error": "invalid profile file",
                    }
                ]
            }
        )

    page.route("**/api/identities", roster)
    page.goto(f"{page.url.rsplit('/', 1)[0]}/profile/builder")
    page.get_by_role("heading", name="Builder", exact=True).wait_for()
    assert page.get_by_text("invalid profile file", exact=False).is_visible()
    assert page.get_by_text("Role", exact=True).is_visible()
    assert page.get_by_text("Builder", exact=True).count() >= 2
    assert builder.read_bytes() == b"name = [invalid\n"
    assert reviewer.read_bytes() == reviewer_before
