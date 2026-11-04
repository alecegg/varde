"""Agent-containment credential: pairing, cookie, CSRF, and the `user_only` gate."""

from __future__ import annotations

import asyncio
import json
import stat
import time

import pytest
from bot_helpers import call
from varde_runner.bot_tokens import TOKEN_HEADER
from varde_runner.user_credential import (
    CODE_TTL_SECONDS,
    COOKIE_NAME,
    CSRF_HEADER,
    MAX_ATTEMPTS,
    Pairing,
    UserCredential,
    code_accepted,
    code_digest,
    cookie_valid,
    csrf_for,
    csrf_valid,
    display_code,
    new_code,
    normalize_code,
    read_pairing_code,
    sign_cookie,
)
from varde_runner.web.app import create_app
from varde_runner.web.pairing_route import cookie_secure

NOW = 1_000_000.0
LOCAL = {"host": "127.0.0.1:8765", "origin": "http://127.0.0.1:8765"}
APPROVE = "/api/plans/p1/merge-approval"


def test_codes_normalise_and_digest_ignores_case_dashes_and_spaces() -> None:
    code = new_code()
    assert len(code) == 8
    assert code_digest(display_code(code).lower()) == code_digest(code)
    assert normalize_code(" ab-cd ") == "ABCD"


def test_code_acceptance_checks_expiry_attempts_and_consumption() -> None:
    pairing = Pairing(
        key="s", code_digest=code_digest("ABCD2345"), code_expires_at=NOW + 10
    )
    assert code_accepted(pairing, "abcd-2345", NOW)
    assert not code_accepted(pairing, "WRONG234", NOW)
    assert not code_accepted(pairing, "ABCD2345", NOW + 10)
    burned = Pairing("s", pairing.code_digest, pairing.code_expires_at, MAX_ATTEMPTS)
    assert not code_accepted(burned, "ABCD2345", NOW)
    assert not code_accepted(Pairing(key="s"), "ABCD2345", NOW)


def test_cookie_and_csrf_are_signed_expire_and_bind_to_each_other() -> None:
    cookie = sign_cookie("secret", NOW + 100, "nonce")
    assert cookie_valid("secret", cookie, NOW)
    assert not cookie_valid("other", cookie, NOW)
    assert not cookie_valid("secret", cookie, NOW + 100)
    assert not cookie_valid("secret", cookie[:-1] + "0", NOW)
    assert not cookie_valid("secret", "garbage", NOW)
    assert not cookie_valid("secret", None, NOW)
    token = csrf_for("secret", cookie)
    assert csrf_valid("secret", cookie, token)
    assert not csrf_valid("secret", cookie, None)
    assert not csrf_valid("secret", cookie, csrf_for("secret", "other-cookie"))


@pytest.fixture
def credential(tmp_path):
    return UserCredential(tmp_path / "state" / "user-credential.json")


def test_pairing_happens_once_and_the_file_is_private(credential) -> None:
    code = credential.start(NOW)
    assert code is not None
    mode = stat.S_IMODE(credential.path.stat().st_mode)
    assert mode == 0o600
    assert credential.pair("WRONG-CODE", NOW) is None
    cookie = credential.pair(code, NOW)
    assert cookie is not None and credential.cookie_ok(cookie, NOW)
    assert credential.pair(code, NOW) is None
    assert credential.start(NOW + 1) is None
    assert credential.cookie_ok(cookie, NOW + 1)


def test_wrong_codes_burn_the_code_and_a_restart_issues_a_new_one(credential) -> None:
    code = credential.start(NOW)
    assert code is not None
    for _ in range(MAX_ATTEMPTS):
        assert credential.pair("WRONG-CODE", NOW) is None
    assert credential.pair(code, NOW) is None
    fresh = credential.start(NOW)
    assert fresh is not None and credential.pair(fresh, NOW) is not None


def test_an_expired_code_is_refused(credential) -> None:
    code = credential.start(NOW)
    assert code is not None
    assert credential.pair(code, NOW + CODE_TTL_SECONDS) is None


@pytest.fixture
def app(credential):
    credential.start(time.time())
    return create_app(
        data_dir=credential.path.parent / "data",
        bound_port=8765,
        user_credential=credential,
        require_user_pairing=True,
    )


def headers_with(cookie: str | None, csrf: str | None) -> dict[str, str]:
    headers = dict(LOCAL)
    if cookie:
        headers["cookie"] = f"{COOKIE_NAME}={cookie}"
    if csrf:
        headers[CSRF_HEADER] = csrf
    return headers


async def call_with_headers(app, method, path, payload, headers):
    """Like `call`, but also return the response headers."""
    body = json.dumps(payload).encode() if payload is not None else b""
    sent = False
    messages: list[dict] = []

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 80),
        },
        receive,
        send,
    )
    start = messages[0]
    text = b"".join(item.get("body", b"") for item in messages[1:])
    return start["status"], json.loads(text), start["headers"]


def pair_in_browser(app, credential_code: str, extra: dict[str, str] | None = None):
    headers_in = {**LOCAL, **(extra or {})}
    status, body, headers = asyncio.run(
        call_with_headers(
            app, "POST", "/api/pairing", {"code": credential_code}, headers_in
        )
    )
    cookies = [v.decode() for k, v in headers if k == b"set-cookie"]
    return status, body, cookies


def test_the_pairing_route_sets_an_httponly_strict_cookie_once(app, credential) -> None:
    status, body, _ = pair_in_browser(app, "WRONG-CODE")
    assert status == 403 and body == {"error": "pairing code refused"}
    code = credential.start(time.time())
    assert code is not None
    status, body, cookies = pair_in_browser(app, code)
    assert status == 200 and body["paired"] is True and body["csrf"]
    (cookie,) = cookies
    assert cookie.startswith(f"{COOKIE_NAME}=")
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    status, _, _ = pair_in_browser(app, code)
    assert status == 403


def test_the_pairing_status_shows_csrf_only_to_the_cookie_holder(
    app, credential
) -> None:
    code = credential.start(time.time())
    assert code is not None
    cookie = credential.pair(code, time.time())
    assert cookie is not None
    _, anonymous = asyncio.run(call(app, "GET", "/api/pairing", None, LOCAL))
    assert anonymous == {"enforced": True, "paired": False, "csrf": None}
    _, paired = asyncio.run(
        call(app, "GET", "/api/pairing", None, headers_with(cookie, None))
    )
    assert paired["paired"] is True and csrf_valid(
        credential_secret(credential), cookie, paired["csrf"]
    )


def credential_secret(credential) -> str:
    return json.loads(credential.path.read_text())["key"]


def test_a_tokenless_call_to_a_user_only_route_is_refused(app) -> None:
    status, body = asyncio.run(call(app, "POST", APPROVE, {"note": "x"}, LOCAL))
    assert status == 403 and "paired user browser" in body["error"]
    _, read = asyncio.run(call(app, "GET", APPROVE, None, LOCAL))
    assert read == {"approval": None}


def test_user_only_writes_work_without_pairing_when_the_gate_is_off(
    credential,
) -> None:
    credential.start(time.time())
    app = create_app(
        data_dir=credential.path.parent / "data-off",
        bound_port=8765,
        user_credential=credential,
        require_user_pairing=False,
    )
    status, body = asyncio.run(call(app, "POST", APPROVE, {"note": "x"}, LOCAL))
    assert status == 201 and body["approval"]["approved_by"] == "user"
    for method, path, payload in (
        ("POST", "/api/runner/restart", {}),
        ("PUT", "/api/runner/config", {"changes": {}}),
        ("POST", "/api/instance-threads/a1/takeover", {}),
    ):
        status, _ = asyncio.run(call(app, method, path, payload, LOCAL))
        assert status != 403, (method, path)
    _, pairing = asyncio.run(call(app, "GET", "/api/pairing", None, LOCAL))
    assert pairing["enforced"] is False and pairing["paired"] is False


def test_user_only_needs_the_cookie_and_the_csrf_header(app, credential) -> None:
    code = credential.start(time.time())
    assert code is not None
    cookie = credential.pair(code, time.time())
    assert cookie is not None
    csrf = csrf_for(credential_secret(credential), cookie)
    cases = {
        "cookie only": headers_with(cookie, None),
        "csrf only": headers_with(None, csrf),
        "wrong csrf": headers_with(cookie, "0" * 64),
        "forged cookie": headers_with("9999999999.n.deadbeef", csrf),
    }
    for name, headers in cases.items():
        status, _ = asyncio.run(call(app, "POST", APPROVE, {}, headers))
        assert status == 403, name
    status, body = asyncio.run(
        call(app, "POST", APPROVE, {"note": "ok"}, headers_with(cookie, csrf))
    )
    assert status == 201 and body["approval"]["approved_by"] == "user"


def test_a_bot_token_cannot_pass_a_user_only_route_even_with_the_cookie(
    app, credential
) -> None:
    code = credential.start(time.time())
    assert code is not None
    cookie = credential.pair(code, time.time())
    assert cookie is not None
    csrf = csrf_for(credential_secret(credential), cookie)
    token = app.state.bot_tokens.issue("bot-session")
    headers = {**headers_with(cookie, csrf), TOKEN_HEADER: token}
    status, _ = asyncio.run(call(app, "POST", APPROVE, {}, headers))
    assert status == 403


def test_other_routes_stay_open_without_the_cookie(app) -> None:
    for path in ("/api/needs-you-count", "/api/queue", "/api/pairing"):
        status, _ = asyncio.run(call(app, "GET", path, None, LOCAL))
        assert status == 200, path


def test_an_app_without_a_credential_is_unchanged(tmp_path) -> None:
    app = create_app(data_dir=tmp_path / "data", bound_port=8765)
    status, _ = asyncio.run(call(app, "POST", APPROVE, {}, LOCAL))
    assert status == 201
    assert all(getattr(r, "path", "") != "/api/pairing" for r in app.routes)


def test_the_code_is_in_a_private_file_until_the_browser_pairs(credential) -> None:
    code = credential.start(NOW)
    assert code is not None
    assert read_pairing_code(credential.path) == code
    assert stat.S_IMODE(credential.code_path.stat().st_mode) == 0o600
    assert credential.pair(code, NOW) is not None
    assert read_pairing_code(credential.path) is None
    assert credential.start(NOW + 1) is None


def test_a_service_without_a_terminal_never_prints_the_code(
    capsys, monkeypatch
) -> None:
    import sys

    import varde_runner

    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    varde_runner._announce_pairing("ABCD-2345")
    output = capsys.readouterr().out
    assert "ABCD-2345" not in output and "varde-runner pairing-code" in output
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    varde_runner._announce_pairing("ABCD-2345")
    assert "ABCD-2345" in capsys.readouterr().out


def test_pairing_is_not_announced_when_the_gate_is_off(capsys) -> None:
    import varde_runner

    varde_runner._announce_pairing("ABCD-2345", require_user_pairing=False)
    assert capsys.readouterr().out == ""


def test_the_cookie_is_secure_only_for_https_requests() -> None:
    assert cookie_secure("https", {})
    assert cookie_secure("http", {"x-forwarded-proto": "https"})
    assert cookie_secure("http", {"x-forwarded-proto": "https, http"})
    assert not cookie_secure("http", {})
    assert not cookie_secure("http", {"x-forwarded-proto": "http"})


def test_the_pairing_route_marks_the_cookie_secure_behind_https(
    app, credential
) -> None:
    code = credential.start(time.time())
    assert code is not None
    _, _, cookies = pair_in_browser(app, code, {"x-forwarded-proto": "https"})
    assert "Secure" in cookies[0]


def test_the_pairing_route_leaves_the_cookie_plain_over_local_http(
    app, credential
) -> None:
    code = credential.start(time.time())
    assert code is not None
    _, _, cookies = pair_in_browser(app, code)
    assert cookies and "Secure" not in cookies[0]
