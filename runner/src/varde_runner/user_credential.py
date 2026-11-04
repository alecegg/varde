"""Agent-containment credential for `user_only` routes.

Not a user login. A pairing code is entered once in a browser; the runner then sets a
signed HttpOnly SameSite=Strict cookie. `user_only` routes need that cookie plus a
CSRF header, so a tokenless local process (an agent on loopback) no longer counts as
the user for them. The secret and pairing state live in one 0600 file in the runner
state dir, the unpaired code in a second; the code is never logged. An unsandboxed
same-user process can read both, so `docs/sandbox-permissions.md` denies the
directory.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from dataclasses import asdict, dataclass, replace
from pathlib import Path

COOKIE_NAME = "varde_user"
CSRF_HEADER = "x-varde-csrf"
CODE_TTL_SECONDS = 24 * 3600
COOKIE_TTL_SECONDS = 30 * 24 * 3600
MAX_ATTEMPTS = 5
CODE_FILE = "pairing-code"
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8


@dataclass(frozen=True, slots=True)
class Pairing:
    """Persisted pairing state; the code is kept only as a digest."""

    key: str
    code_digest: str | None = None
    code_expires_at: float = 0.0
    attempts: int = 0
    paired_at: float | None = None


def new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def normalize_code(code: str) -> str:
    return "".join(code.split()).replace("-", "").upper()


def display_code(code: str) -> str:
    half = len(code) // 2
    return f"{code[:half]}-{code[half:]}"


def code_digest(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode()).hexdigest()


def code_accepted(pairing: Pairing, code: str, now: float) -> bool:
    """True when the code matches an unexpired, unburned, unused pairing code."""
    if pairing.code_digest is None or pairing.attempts >= MAX_ATTEMPTS:
        return False
    if now >= pairing.code_expires_at:
        return False
    return hmac.compare_digest(pairing.code_digest, code_digest(code))


def _sign(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def sign_cookie(secret: str, expires_at: float, nonce: str) -> str:
    payload = f"{int(expires_at)}.{nonce}"
    return f"{payload}.{_sign(secret, payload)}"


def cookie_valid(secret: str, value: str | None, now: float) -> bool:
    if not value:
        return False
    expires, _, rest = value.partition(".")
    nonce, _, signature = rest.partition(".")
    if not (expires.isdigit() and nonce and signature):
        return False
    if now >= int(expires):
        return False
    expected = _sign(secret, f"{expires}.{nonce}")
    return hmac.compare_digest(expected, signature)


def csrf_for(secret: str, cookie: str) -> str:
    return _sign(secret, f"csrf:{cookie}")


def csrf_valid(secret: str, cookie: str | None, header: str | None) -> bool:
    if not cookie or not header:
        return False
    return hmac.compare_digest(csrf_for(secret, cookie), header)


def _load(path: Path) -> Pairing | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Pairing(**data)
    except OSError, ValueError, TypeError:
        return None


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temp, path)


def _write(path: Path, pairing: Pairing) -> None:
    _write_private(path, json.dumps(asdict(pairing)))


def read_pairing_code(state_file: Path) -> str | None:
    """The unpaired code the runner wrote beside its state file, if any."""
    try:
        return state_file.with_name(CODE_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None


class MergeApproverSecret:
    """Runner secret used only by the main agent approval endpoint."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def start(self) -> str:
        """Create a private random secret once and return its value."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            value = self.path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            value = ""
        if not value:
            value = secrets.token_urlsafe(32)
            _write_private(self.path, value)
        else:
            self.path.chmod(0o600)
        return value

    def matches(self, candidate: str | None) -> bool:
        if not candidate:
            return False
        try:
            expected = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        return hmac.compare_digest(expected, candidate)


class UserCredential:
    """File-backed pairing state; every transition runs under one lock."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    @property
    def code_path(self) -> Path:
        return self.path.with_name(CODE_FILE)

    def start(self, now: float) -> str | None:
        """Prepare at runner start; return a fresh code when unpaired.

        The code is also written to a 0600 file beside the state file, so the
        user can read it when the runner has no terminal (a service).
        """
        with self._lock:
            pairing = _load(self.path) or Pairing(key=secrets.token_hex(32))
            if pairing.paired_at is not None:
                _write(self.path, pairing)
                self.code_path.unlink(missing_ok=True)
                return None
            code = new_code()
            _write_private(self.code_path, display_code(code))
            _write(
                self.path,
                replace(
                    pairing,
                    code_digest=code_digest(code),
                    code_expires_at=now + CODE_TTL_SECONDS,
                    attempts=0,
                ),
            )
            return display_code(code)

    def pair(self, code: str, now: float) -> str | None:
        """Consume the code and return a cookie value, or None when refused."""
        with self._lock:
            pairing = _load(self.path)
            if pairing is None or pairing.code_digest is None:
                return None
            if not code_accepted(pairing, code, now):
                _write(self.path, replace(pairing, attempts=pairing.attempts + 1))
                return None
            _write(
                self.path, replace(pairing, code_digest=None, paired_at=now, attempts=0)
            )
            self.code_path.unlink(missing_ok=True)
            return sign_cookie(
                pairing.key, now + COOKIE_TTL_SECONDS, secrets.token_hex(16)
            )

    def cookie_ok(self, value: str | None, now: float) -> bool:
        pairing = _load(self.path)
        return pairing is not None and cookie_valid(pairing.key, value, now)

    def request_ok(self, cookie: str | None, csrf: str | None, now: float) -> bool:
        pairing = _load(self.path)
        if pairing is None or not cookie_valid(pairing.key, cookie, now):
            return False
        return csrf_valid(pairing.key, cookie, csrf)

    def csrf_token(self, cookie: str | None, now: float) -> str | None:
        pairing = _load(self.path)
        if pairing is None or not cookie_valid(pairing.key, cookie, now):
            return None
        return csrf_for(pairing.key, cookie or "")
