from __future__ import annotations

import gzip
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from varde_toz import fetch
from varde_toz.commands import fetch as fetch_command

FIXTURES = Path(__file__).parent / "fixtures" / "toz-core"


def test_ca_bundle_resolution_and_loading():
    cert = FIXTURES / "ca-root.pem"
    chosen = fetch.resolve_bundle("/from/env.pem", (str(cert),))
    assert chosen == Path("/from/env.pem")
    assert fetch.resolve_bundle("", ("/no/such/file", str(cert))) == cert
    assert fetch.resolve_bundle(None, ("/no/such/file",)) is None
    assert fetch.resolve_bundle(None, ("/no/such/file", str(cert))) == cert
    context = fetch.ssl.SSLContext(fetch.ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(cert))
    empty = FIXTURES.parent / "empty-ca.pem"
    empty.write_text("# no certificates here\n")
    try:
        import os

        previous = os.environ.get("SSL_CERT_FILE")
        os.environ["SSL_CERT_FILE"] = str(empty)
        try:
            fetch.ca_bundle_status()
        except ValueError as exc:
            assert "no certificates" in str(exc)
        else:
            raise AssertionError("expected empty CA bundle to fail")
        finally:
            if previous is None:
                os.environ.pop("SSL_CERT_FILE", None)
            else:
                os.environ["SSL_CERT_FILE"] = previous
    finally:
        empty.unlink(missing_ok=True)


class Handler(BaseHTTPRequestHandler):
    requests = 0
    status = 200
    content_type = "text/html; charset=utf-8"
    body = (
        b"<html><head><title>Widget Docs</title></head><body><nav>Home</nav><main>"
        b"<h1>Widget Docs</h1><p>The widget crate provides a Widget type "
        b"configured with a builder.</p><h2>Install</h2><pre>cargo add widget</pre>"
        b"<p>Then call Widget.builder and set options.</p></main>"
        b"<footer>Privacy</footer>"
        b"</body></html>"
    )

    def do_GET(self):
        type(self).requests += 1
        self.send_response(type(self).status)
        self.send_header("Content-Type", type(self).content_type)
        self.send_header("ETag", '"fixture"')
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, format: str, *args: object) -> None:
        pass


def server_url():
    Handler.requests = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}/docs"


def test_html_conversion_removes_chrome_and_keeps_title_content():
    text, title = fetch.to_text(
        "text/html", Handler.body.decode(), "http://example.test/docs"
    )
    assert title == "Widget Docs"
    assert "Widget Docs" in text
    assert "cargo add widget" in text
    assert "Home" not in text
    assert "Privacy" not in text


def test_rust_readability_fixtures_keep_article_table_and_unicode_content():
    article, title = fetch.to_text(
        "text/html",
        (FIXTURES / "html/article.html").read_text(),
        "https://example.com/post",
    )
    assert title == "Understanding Ownership in Rust | Example Blog"
    assert all(
        value in article
        for value in (
            "Understanding Ownership",
            "Borrowing in practice",
            "fn longest",
            "Trait objects when you need them",
        )
    )
    assert all(
        value not in article
        for value in (
            "Accept all cookies",
            "Related posts",
            "Great post",
            "Privacy policy",
            "Sponsored",
            "analytics",
        )
    )

    table, _ = fetch.to_text(
        "text/html",
        (FIXTURES / "html/table.html").read_text(),
        "https://example.com/post",
    )
    assert all(
        value in table
        for value in ("| serde", "Serialization framework", "| rayon", "snapshot")
    )
    assert "Site footer" not in table

    short, title = fetch.to_text(
        "text/html",
        (FIXTURES / "html/short.html").read_text(),
        "https://example.com/post",
    )
    assert title == "Status"
    assert all(value in short for value in ("All systems operational", "No incidents."))
    assert all(value not in short for value in ("Menu", "Contact"))

    odd, title = fetch.to_text(
        "text/html",
        (FIXTURES / "html/odd.html").read_text(),
        "https://example.com/post",
    )
    assert title == "Notes on café & 日本語"
    assert all(
        value in odd
        for value in ("First paragraph", "日本語のテキスト", "item two", "café", "lait")
    )
    assert "broken" not in odd


def test_htmd_readme_fixture_remains_plain_text():
    readme = (FIXTURES / "htmd-readme.md").read_text()
    assert fetch.to_text(
        "text/markdown", readme, "https://example.com/htmd-readme"
    ) == (readme, None)


def test_json_pretty_print_and_plain_text_passthrough():
    pretty, title = fetch.to_text("application/json", '{"b":true,"a":[1,2]}', "u")
    assert pretty == '{\n  "a": [\n    1,\n    2\n  ],\n  "b": true\n}'
    assert title is None
    assert fetch.to_text("text/plain", "plain  text\n", "u") == ("plain  text\n", None)


def test_normalize_url_removes_fragment_only():
    assert fetch.normalize_url(" https://a/b#frag ") == "https://a/b"
    assert fetch.normalize_url("https://a/b?q=1") == "https://a/b?q=1"


@pytest.mark.usefixtures("inet_socket_bind")
def test_local_http_fetch_caches_and_ttl_expires(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "config"))
    server, url = server_url()
    try:
        fetched = fetch.fetch(url, ttl_secs=3600)
        assert fetched.meta["title"] == "Widget Docs"
        fetch.cache_put(fetched)
        hit = fetch.fetch(url, ttl_secs=3600)
        assert hit.from_cache and hit.text == fetched.text
        assert Handler.requests == 1
        assert fetch.fetch(url, ttl_secs=0).from_cache is False
        assert Handler.requests == 2
        fetched.meta["fetched_at"] = int(time.time()) - 100
        fetch.cache_put(fetched)
        assert fetch.cache_get(url, 50) is None
        assert fetch.cache_sweep(50) == 1
        assert fetch.cache_get(url, 3600) is None
    finally:
        server.shutdown()


@pytest.mark.usefixtures("inet_socket_bind")
def test_force_skips_existing_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "config"))
    server, url = server_url()
    try:
        first = fetch.fetch(url)
        fetch.cache_put(first)
        forced = fetch.fetch(url, force=True)
        assert not forced.from_cache
        assert Handler.requests == 2
    finally:
        server.shutdown()


def test_cache_metadata_redacts_credentials_queries_and_body(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "config"))
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.toml").write_text(
        '[redact]\npatterns = ["secret123"]\n'
    )
    url = "https://alice:password@example.test/docs?token=secret123"
    value = fetch.Fetched(
        url,
        {
            "url": url,
            "final_url": url,
            "content_type": "text/plain",
            "fetched_at": int(time.time()),
            "title": None,
            "etag": None,
            "handle": None,
            "project_key": None,
        },
        "secret123 body",
    )
    fetch.cache_put(value)
    meta_path = next(fetch.cache_dir().glob("*.meta"))
    body_path = meta_path.with_suffix(".body")
    raw = meta_path.read_text()
    assert all(secret not in raw for secret in ("alice", "password", "secret123"))
    assert "secret123" not in body_path.read_text()
    cached = fetch.cache_get(url, 60)
    assert cached is not None
    assert cached.request_url == url


@pytest.mark.usefixtures("inet_socket_bind")
def test_http_status_and_binary_content_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "config"))
    server, url = server_url()
    try:
        Handler.status = 503
        with pytest.raises(ValueError, match="HTTP 503"):
            fetch.fetch(url, ttl_secs=0)
        Handler.status = 200
        Handler.content_type = "application/pdf"
        with pytest.raises(ValueError, match="unsupported content type"):
            fetch.fetch(url, ttl_secs=0)
        Handler.content_type = "text/html; charset=utf-8"
        assert fetch.fetch(url, ttl_secs=0).meta["title"] == "Widget Docs"
    finally:
        Handler.status = 200
        Handler.content_type = "text/html; charset=utf-8"
        server.shutdown()


def test_fetch_rejects_declared_and_streamed_bodies_over_limit(monkeypatch):
    class Response:
        status = 200

        def __init__(self, data, headers):
            self.data = io.BytesIO(data)
            self.headers = headers

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def geturl(self):
            return "http://example.test/body"

        def read(self, size=-1):
            return self.data.read(size)

    oversized = b"x" * (fetch.MAX_BODY + 1)
    monkeypatch.setattr(
        fetch.urllib.request,
        "urlopen",
        lambda *a, **k: Response(
            b"", {"Content-Type": "text/plain", "Content-Length": str(len(oversized))}
        ),
    )
    try:
        fetch.fetch("http://example.test/body", ttl_secs=0)
    except ValueError as exc:
        assert "over the 20971520 byte limit" in str(exc)
    else:
        raise AssertionError("expected declared body size rejection")

    monkeypatch.setattr(
        fetch.urllib.request,
        "urlopen",
        lambda *a, **k: Response(oversized, {"Content-Type": "text/plain"}),
    )
    try:
        fetch.fetch("http://example.test/body", ttl_secs=0)
    except ValueError as exc:
        assert "over the 20971520 byte limit" in str(exc)
    else:
        raise AssertionError("expected streamed body size rejection")

    compressed = gzip.compress(oversized)
    monkeypatch.setattr(
        fetch.urllib.request,
        "urlopen",
        lambda *a, **k: Response(
            compressed,
            {
                "Content-Type": "text/plain",
                "Content-Encoding": "gzip",
            },
        ),
    )
    try:
        fetch.fetch("http://example.test/body", ttl_secs=0)
    except ValueError as exc:
        assert "over the 20971520 byte limit" in str(exc)
    else:
        raise AssertionError("expected decoded compressed size rejection")


def test_cache_clear_removes_metadata_and_body(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "config"))
    value = fetch.Fetched(
        "https://x/current",
        {
            "url": "https://x/current",
            "final_url": "https://x/current",
            "content_type": "text/plain",
            "fetched_at": int(time.time()),
            "title": None,
            "etag": None,
            "handle": None,
            "project_key": None,
        },
        "body",
    )
    fetch.cache_put(value)
    assert fetch.cache_clear() == 1
    assert fetch.cache_get(value.request_url, 3600) is None


def test_fetch_rejects_negative_concurrency_before_request(capsys):
    status = fetch_command.main(["http://example.test/page", "--concurrency", "-1"])

    assert status == 2
    assert "unexpected argument '-1' found" in capsys.readouterr().err


@pytest.mark.usefixtures("inet_socket_bind")
def test_fetch_command_reports_multiple_urls_in_input_order(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "config"))
    server, url = server_url()
    urls = [f"{url}/{index}" for index in range(3)]
    try:
        assert fetch_command.main(["--concurrency", "2", *urls]) == 0
    finally:
        server.shutdown()
    output = capsys.readouterr().out
    positions = [output.index(f"=== {url} ===") for url in urls]
    assert positions == sorted(positions)


def test_legacy_cache_migration_redacts_and_preserves_body(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "config"))
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.toml").write_text(
        '[redact]\npatterns = ["secret123"]\n'
    )
    url = "https://user:password@example.test/docs?token=secret123"
    folder = fetch.cache_dir()
    folder.mkdir(parents=True)
    import blake3

    old_meta = folder / f"{blake3.blake3(url.encode()).hexdigest()}.meta"
    old_body = old_meta.with_suffix(".body")
    old_meta.write_text(
        json.dumps(
            {
                "url": url,
                "final_url": url,
                "content_type": "text/plain",
                "fetched_at": int(time.time()),
                "title": "secret123",
                "etag": None,
                "handle": "same-handle",
                "project_key": "project",
            }
        )
    )
    old_body.write_text("cached body")
    assert fetch.migrate_legacy_cache() == 1
    assert not old_meta.exists() and not old_body.exists()
    new_meta = next(fetch.cache_dir().glob("*.meta"))
    new_body = new_meta.with_suffix(".body")
    assert "secret123" not in new_meta.read_text()
    assert new_body.read_text() == "cached body"


def test_legacy_cache_migration_recovers_existing_body_and_rejects_bad_metadata(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "config"))
    url = "https://example.test/docs?token=private"
    import blake3

    folder = fetch.cache_dir()
    folder.mkdir(parents=True)
    legacy = folder / f"{blake3.blake3(url.encode()).hexdigest()}.meta"
    legacy.with_suffix(".body").write_text("same body")
    meta = {
        "url": url,
        "final_url": url,
        "content_type": "text/plain",
        "fetched_at": int(time.time()),
        "title": None,
        "etag": None,
        "handle": "old-handle",
        "project_key": None,
    }
    legacy.write_text(json.dumps(meta))
    fetch.cache_put(fetch.Fetched(url, meta, "same body"))
    keyed_meta = next(
        path for path in fetch.cache_dir().glob("*.meta") if path != legacy
    )
    keyed_meta.unlink()
    assert fetch.migrate_legacy_cache() == 1
    keyed_meta = next(fetch.cache_dir().glob("*.meta"))
    assert keyed_meta.with_suffix(".body").read_text() == "same body"
    assert not legacy.exists()

    broken = folder / "broken.meta"
    broken.write_text("{not json")
    try:
        fetch.migrate_legacy_cache()
    except ValueError as exc:
        assert "parsing fetch cache metadata" in str(exc)
    else:
        raise AssertionError("expected invalid legacy metadata rejection")
    assert broken.exists()
