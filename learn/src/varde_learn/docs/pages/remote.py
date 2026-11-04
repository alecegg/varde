"""Admission rules for a non-loopback bind: access key, cookie and edit gate. Pure."""

from __future__ import annotations

import hmac
from http.cookies import CookieError, SimpleCookie
from urllib.parse import parse_qs, urlsplit

COOKIE_PREFIX = "varde_access_"
# Paths that need the cookie on a non-loopback bind; static assets stay open.
GATED_GET = ("/", "/events", "/block")
EDIT_ROUTES = frozenset({"/edit", "/accept"})


def entry_url(base_url: str, key: str) -> str:
    return f"{base_url}?k={key}"


def is_gated_get(path: str) -> bool:
    return path in GATED_GET or path.startswith("/media/")


def key_matches(sent: str, key: str) -> bool:
    return hmac.compare_digest(sent.encode(), key.encode())


def handshake_key(raw_path: str) -> str | None:
    """Return the `k` value of a request for `/` that carries one, else None."""
    parts = urlsplit(raw_path)
    if parts.path != "/":
        return None
    values = parse_qs(parts.query).get("k")
    return values[0] if values else None


def cookie_name(port: int) -> str:
    """Cookies are scoped by host, not port: one name per server port."""
    return f"{COOKIE_PREFIX}{port}"


def cookie_value(cookie_header: str | None, port: int) -> str:
    if not cookie_header:
        return ""
    jar: SimpleCookie = SimpleCookie()
    try:
        jar.load(cookie_header)
    except CookieError:
        return ""
    morsel = jar.get(cookie_name(port))
    return morsel.value if morsel else ""


def has_access(cookie_header: str | None, key: str, port: int) -> bool:
    return key_matches(cookie_value(cookie_header, port), key)


def set_cookie_header(key: str, port: int) -> str:
    """HttpOnly, SameSite=Strict, Path=/; no Secure (http over WireGuard)."""
    return f"{cookie_name(port)}={key}; HttpOnly; SameSite=Strict; Path=/"


def edit_denied(path: str, remote: bool, allow_edit: bool) -> bool:
    return remote and not allow_edit and path in EDIT_ROUTES
