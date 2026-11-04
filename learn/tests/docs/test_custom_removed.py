"""The `custom` block is gone: check names it, the page shows an error card."""

from __future__ import annotations

import http.client
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from varde_learn.docs import cli
from varde_learn.docs.pages.assemble import assemble_page
from varde_learn.docs.pages.serve import PageServer

DOC = "# Plan\n\nIntro.\n\n```custom id=widget\n<p>hi</p>\n```\n"


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    path = tmp_path / "plan.md"
    path.write_text(DOC, encoding="utf-8")
    return path


@pytest.fixture
def server(doc: Path) -> Iterator[PageServer]:
    srv = PageServer(doc, 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def get(srv: PageServer, path: str) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("GET", path, headers={"Host": f"127.0.0.1:{srv.port}"})
    response = conn.getresponse()
    out = response.status, dict(response.getheaders()), response.read()
    conn.close()
    return out


def test_check_exits_1_naming_the_rule_and_the_fence_line(
    doc: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.run(["blocks", "--check", str(doc)]) == 1
    out = capsys.readouterr().out
    assert f"{doc}:5: custom-block-removed:" in out


def test_check_passes_without_a_custom_fence(tmp_path: Path) -> None:
    clean = tmp_path / "clean.md"
    clean.write_text("# Plan\n\nNo blocks.\n", encoding="utf-8")
    assert cli.run(["blocks", "--check", str(clean)]) == 0


def test_rendered_page_shows_the_error_card_and_no_frame(doc: Path) -> None:
    page = assemble_page(doc, token="t")  # noqa: S106
    assert "vb-card vb-error" in page and "custom block removed" in page
    assert (
        "<iframe" not in page and "&lt;p&gt;hi" not in page and "<p>hi</p>" not in page
    )


def test_sandbox_route_is_gone(server: PageServer) -> None:
    digest = "0" * 64
    assert get(server, f"/sandbox/{digest}")[0] == 404
    assert get(server, "/static/sandbox.js")[0] == 404


def test_csp_has_no_sandbox_frame_or_inline_script(server: PageServer) -> None:
    csp = get(server, "/")[1]["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "sandbox" not in csp and "frame-src" not in csp
    assert "unsafe-inline" not in csp.split("script-src", 1)[1].split(";", 1)[0]
