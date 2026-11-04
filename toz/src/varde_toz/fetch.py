"""HTTP fetching, HTML conversion, and the keyed fetch cache."""

from __future__ import annotations

import contextlib
import html
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar

from bs4 import BeautifulSoup
from markdownify import markdownify

from . import metadata
from .chunk import strip_ansi
from .config import config_dir
from .redact_toz import configured_redactor, redact_configured

DEFAULT_TTL_SECS = 24 * 60 * 60
MAX_BODY = 20 * 1024 * 1024
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 "
    "Safari/537.36 toz/0.1"
)
CA_BUNDLES = (
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/ca-bundle.pem",
)


@dataclass
class Fetched:
    request_url: str
    meta: dict[str, Any]
    text: str
    from_cache: bool = False


def normalize_url(url: str) -> str:
    return url.strip().split("#", 1)[0]


def cache_dir() -> Path:
    return config_dir() / "cache"


def resolve_bundle(
    explicit: str | None, candidates: tuple[str, ...] = CA_BUNDLES
) -> Path | None:
    if explicit:
        return Path(explicit)
    return next((Path(path) for path in candidates if Path(path).is_file()), None)


def ca_bundle_path() -> Path | None:
    return resolve_bundle(os.environ.get("SSL_CERT_FILE"))


def ca_bundle_status() -> tuple[Path, int] | None:
    path = ca_bundle_path()
    if path is None:
        return None
    pem = path.read_bytes()
    count = len(re.findall(rb"-----BEGIN CERTIFICATE-----", pem))
    if count == 0:
        raise ValueError(f"CA bundle {path} contains no certificates")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(path))
    return path, count


def _ssl_context() -> ssl.SSLContext | None:
    path = ca_bundle_path()
    if path is None:
        return None
    explicit = bool(os.environ.get("SSL_CERT_FILE"))
    try:
        return ssl.create_default_context(cafile=str(path))
    except OSError, ssl.SSLError:
        if explicit:
            raise
        return None


def _cache_paths(url: str) -> tuple[Path, Path]:
    folder = cache_dir()
    key = metadata.cache_key(url, config_dir())
    return folder / f"{key}.meta", folder / f"{key}.body"


def cache_get(url: str, ttl_secs: int) -> Fetched | None:
    if ttl_secs == 0:
        return None
    try:
        meta_path, body_path = _cache_paths(url)
        meta = json.loads(meta_path.read_text())
        age = int(time.time()) - int(meta["fetched_at"])
        if age < 0 or age > ttl_secs:
            return None
        return Fetched(url, meta, body_path.read_text(), True)
    except OSError, ValueError, KeyError, TypeError:
        return None


def cache_put(fetched: Fetched) -> None:
    meta_path, body_path = _cache_paths(fetched.request_url)
    meta_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    meta = dict(fetched.meta)
    redactor = configured_redactor(Path.cwd())
    meta["url"] = metadata.sanitize_url(
        meta["url"], lambda value: redact_configured(value, redactor)
    )
    meta["final_url"] = metadata.sanitize_url(
        meta["final_url"], lambda value: redact_configured(value, redactor)
    )
    meta["content_type"] = redact_configured(meta["content_type"], redactor)[0]
    for key in ("title", "etag"):
        if meta.get(key) is not None:
            meta[key] = metadata.sanitize_text(
                meta[key], lambda value: redact_configured(value, redactor)
            )
    body = strip_ansi(fetched.text)
    body = redact_configured(body, redactor)[0]
    body_path.write_text(body)
    meta_path.write_text(json.dumps(meta, separators=(",", ":"), ensure_ascii=False))
    with contextlib.suppress(OSError):
        meta_path.parent.chmod(0o700)


def cache_sweep(max_age_secs: int) -> int:
    folder = cache_dir()
    try:
        entries = list(folder.glob("*.meta"))
    except OSError:
        return 0
    cutoff = int(time.time()) - max_age_secs
    removed = 0
    for path in entries:
        try:
            meta = json.loads(path.read_text())
            stale = int(meta["fetched_at"]) < cutoff
        except OSError, ValueError, KeyError, TypeError:
            stale = True
        if stale:
            path.unlink(missing_ok=True)
            path.with_suffix(".body").unlink(missing_ok=True)
            removed += 1
    return removed


def cache_clear() -> int:
    folder = cache_dir()
    if not folder.exists():
        return 0
    removed = 0
    for path in folder.iterdir():
        if path.suffix == ".meta":
            path.unlink()
            removed += 1
        elif path.suffix != ".body":
            continue
        body_path = path.with_suffix(".body")
        body_path.unlink(missing_ok=True)
    return removed


def migrate_legacy_cache() -> int:
    folder = cache_dir()
    if not folder.exists():
        return 0
    redactor = configured_redactor(Path.cwd())
    migrated = 0
    for old_meta_path in folder.glob("*.meta"):
        try:
            meta = json.loads(old_meta_path.read_text())
        except (OSError, ValueError) as exc:
            raise ValueError(f"parsing fetch cache metadata: {exc}") from exc
        original_url = meta.get("url")
        if (
            not isinstance(original_url, str)
            or old_meta_path.stem
            != __import__("blake3").blake3(original_url.encode()).hexdigest()
        ):
            continue
        old_body_path = old_meta_path.with_suffix(".body")
        if not old_body_path.is_file():
            raise ValueError("incomplete legacy fetch cache entry")
        new_meta_path, new_body_path = _cache_paths(original_url)
        if new_meta_path.exists():
            if not new_body_path.is_file():
                raise ValueError("incomplete keyed fetch cache entry")
        else:
            if (
                new_body_path.exists()
                and old_body_path.read_bytes() != new_body_path.read_bytes()
            ):
                raise ValueError("conflicting keyed fetch cache body")
            if not new_body_path.exists():
                new_body_path.hardlink_to(old_body_path)
            meta["url"] = metadata.sanitize_url(
                meta["url"], lambda value: redact_configured(value, redactor)
            )
            meta["final_url"] = metadata.sanitize_url(
                meta["final_url"], lambda value: redact_configured(value, redactor)
            )
            meta["content_type"] = redact_configured(
                meta.get("content_type", ""), redactor
            )[0]
            for name in ("title", "etag"):
                if meta.get(name) is not None:
                    meta[name] = metadata.sanitize_text(
                        meta[name], lambda value: redact_configured(value, redactor)
                    )
            key = meta.get("project_key")
            if key is not None:
                meta["project_key"] = metadata.project_identity(key, config_dir())
            new_meta_path.write_text(json.dumps(meta, separators=(",", ":")))
        old_body_path.unlink(missing_ok=True)
        old_meta_path.unlink(missing_ok=True)
        migrated += 1
    return migrated


def _title(html_text: str) -> str | None:
    match = re.search(
        r"<title\b[^>]*>(.*?)</title\s*>", html_text, re.IGNORECASE | re.DOTALL
    )
    if not match:
        return None
    value = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))).split())
    return value or None


class _PruneChrome(HTMLParser):
    skip: ClassVar[frozenset[str]] = frozenset(
        {
            "script",
            "style",
            "noscript",
            "svg",
            "iframe",
            "nav",
            "header",
            "footer",
            "aside",
        }
    )

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self.depth:
            if tag in self.skip:
                self.depth += 1
            return
        if tag in self.skip:
            self.depth = 1
            return
        if tag == "title":
            self.parts.append("<p>")
            return
        attrs_text = "".join(
            f' {name}="{html.escape(value or "", quote=True)}"' for name, value in attrs
        )
        self.parts.append(f"<{tag}{attrs_text}>")

    def handle_endtag(self, tag):
        if self.depth:
            if tag in self.skip:
                self.depth -= 1
            return
        if tag == "title":
            self.parts.append("</p>")
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(html.escape(data))


def _html_markdown(body: str) -> tuple[str, str | None]:
    title = _title(body)
    soup = BeautifulSoup(body, "html.parser")
    article = soup.find("article") or soup.find("main")
    if article is not None:
        extracted = markdownify(str(article), heading_style="ATX", bullets="-")
        extracted = _tidy(extracted)
        if len(extracted) >= 200:
            content = f"# {title}\n\n{extracted}" if title else extracted
            return f"{content}\n", title
    parser = _PruneChrome()
    parser.feed(body)
    markdown = _tidy(
        markdownify("".join(parser.parts), heading_style="ATX", bullets="-")
    )
    return f"{markdown}\n", title


def _tidy(markdown: str) -> str:
    markdown = "\n".join(line.rstrip() for line in markdown.splitlines())
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()


def to_text(mime: str, body: str, url: str) -> tuple[str, str | None]:
    mime = mime.split(";", 1)[0].strip().lower()
    if mime in ("text/html", "application/xhtml+xml") or (
        mime in ("text/plain", "application/octet-stream")
        and body.lstrip()[:256].lower().startswith(("<!doctype html", "<html"))
    ):
        return _html_markdown(body)
    if mime in ("application/json", "text/json") or mime.endswith("+json"):
        try:
            return json.dumps(
                json.loads(body), indent=2, ensure_ascii=False, sort_keys=True
            ), None
        except ValueError, TypeError:
            return body, None
    return body, None


def _binary_mime(mime: str) -> bool:
    return mime.startswith(("image/", "audio/", "video/", "font/")) or mime in {
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "application/gzip",
        "application/x-tar",
        "application/wasm",
    }


def _read_limited_body(response, encoding: str) -> bytes:
    encoding = encoding.strip().lower()
    if encoding not in ("gzip", "deflate"):
        data = response.read(MAX_BODY + 1)
        if len(data) > MAX_BODY:
            raise ValueError(
                f"body is {len(data)} bytes, over the {MAX_BODY} byte limit"
            )
        return data
    window = zlib.MAX_WBITS | 16 if encoding == "gzip" else zlib.MAX_WBITS
    decoder = zlib.decompressobj(window)
    decoded = bytearray()
    while True:
        block = response.read(64 * 1024)
        if not block:
            break
        decoded.extend(decoder.decompress(block, MAX_BODY + 1 - len(decoded)))
        if len(decoded) > MAX_BODY or decoder.unconsumed_tail:
            raise ValueError(f"body is over the {MAX_BODY} byte limit")
    decoded.extend(decoder.flush(MAX_BODY + 1 - len(decoded)))
    if len(decoded) > MAX_BODY:
        raise ValueError(f"body is over the {MAX_BODY} byte limit")
    if not decoder.eof:
        raise ValueError("incomplete compressed response body")
    return bytes(decoded)


def fetch(url: str, ttl_secs: int = DEFAULT_TTL_SECS, force: bool = False) -> Fetched:
    url = normalize_url(url)
    if urllib.parse.urlsplit(url).scheme not in {"http", "https"}:
        raise ValueError("only HTTP and HTTPS URLs are supported")
    if not force:
        cached = cache_get(url, ttl_secs)
        if cached is not None:
            return cached
    request = urllib.request.Request(  # noqa: S310 - URL scheme is checked before creating the request.
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/json,"
                "text/*;q=0.9,*/*;q=0.5"
            ),
            "Accept-Encoding": "gzip, deflate",
        },
    )
    try:
        response = urllib.request.urlopen(request, timeout=30, context=_ssl_context())  # noqa: S310 - URL scheme is checked before opening the request.
    except urllib.error.HTTPError as exc:
        raise ValueError(f"GET {url}: HTTP {exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise ValueError(f"GET {url}: {exc}") from exc
    with response:
        final_url = response.geturl()
        headers = response.headers
        content_type = headers.get("Content-Type", "application/octet-stream")
        mime = content_type.split(";", 1)[0].strip().lower()
        if _binary_mime(mime):
            raise ValueError(f"GET {url}: unsupported content type {mime}")
        length = headers.get("Content-Length")
        if length and int(length) > MAX_BODY:
            raise ValueError(
                f"GET {url}: body is {length} bytes, over the {MAX_BODY} byte limit"
            )
        try:
            data = _read_limited_body(
                response, headers.get("Content-Encoding", "identity")
            )
        except (ValueError, zlib.error) as exc:
            raise ValueError(f"GET {url}: {exc}") from exc
    text, title = to_text(mime, data.decode("utf-8", "replace"), final_url)
    return Fetched(
        url,
        {
            "url": url,
            "final_url": final_url,
            "content_type": content_type,
            "fetched_at": int(time.time()),
            "title": title,
            "etag": headers.get("ETag"),
            "handle": None,
            "project_key": None,
        },
        text,
    )
