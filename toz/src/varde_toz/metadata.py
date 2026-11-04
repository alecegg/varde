"""Private keyed identities stored alongside a toz database."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NoReturn


def _raise_invalid_url() -> NoReturn:
    raise ValueError("not URL")


def _key(dir: str | Path) -> bytes:
    folder = Path(dir)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / "metadata.key"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        data = path.read_bytes()
    else:
        data = os.urandom(32)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    if len(data) != 32:
        raise ValueError(f"invalid metadata identity key at {path}")
    return data


def identity_at(dir: str | Path, original: str) -> str:
    try:
        import blake3  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "the blake3 package is required for Rust-compatible metadata identities"
        ) from exc
    return blake3.blake3(
        b"capture-identity\0" + original.encode(), key=_key(dir)
    ).hexdigest()


def sanitize_text(text: str, redactor) -> str:
    url = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s<>]+")
    safe = url.sub(lambda match: sanitize_url(match.group(0), redactor), text)
    return redactor(safe)[0]


def sanitize_url(value: str, redactor) -> str:
    if "@" in value and "://" not in value:
        return "[redacted:url]"
    try:
        from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

        parts = urlsplit(value)
        if not parts.scheme or not parts.netloc:
            _raise_invalid_url()
        hostname = parts.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        if parts.port:
            hostname += f":{parts.port}"
        query = "&".join(
            f"{quote(key)}=%5Bredacted%5D"
            for key, _ in parse_qsl(parts.query, keep_blank_values=True)
        )
        result = urlunsplit(
            (
                parts.scheme,
                hostname,
                parts.path,
                query,
                "%5Bredacted%5D" if parts.fragment else "",
            )
        )
    except ValueError, TypeError:
        if "://" in value:
            scheme = value.split("://", 1)[0]
            return f"{scheme}://[redacted:url]"
        base = value.split("?", 1)[0]
        result = redactor(base)[0] + ("?[redacted]" if "?" in value else "")
    return redactor(result)[0]


def identity(original: str, dir: str | Path | None = None) -> str:
    if dir is None:
        from varde_toz.config import config_dir

        dir = config_dir()
    return identity_at(dir, original)


def cache_key(url: str, dir: str | Path) -> str:
    import blake3  # type: ignore[import-not-found]

    return blake3.blake3(b"fetch-cache\0" + url.encode(), key=_key(dir)).hexdigest()


def project_identity(project_key: str, dir: str | Path) -> str:
    import blake3  # type: ignore[import-not-found]

    return blake3.blake3(
        b"fetch-project\0" + project_key.encode(), key=_key(dir)
    ).hexdigest()
