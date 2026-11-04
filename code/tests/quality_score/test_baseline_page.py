"""Page smoke test: the HTTP/HTML sequence the page performs (no browser)."""

import base64
import hashlib
import http.client
import json
import re
from pathlib import Path

from test_baseline_server import (
    GOOD,
    MISSING,
    NESTED,
    RAW_NAMES,
    client,  # noqa: F401 (fixture)
    data,  # noqa: F401 (fixture)
    req,
    serving,
)
from varde_code.quality_score.calibration import overlay as ov
from varde_code.quality_score.cli import baseline_page as page
from varde_code.quality_score.cli import baseline_service as svc

# Passes the behaviour tests but is deeply nested, so it scores differently.
PASSING_NESTED = (
    "def add(a, b):\n    total = 0\n"
    + "".join("    " * (i + 1) + f"if a > {i - 99}:\n" for i in range(8))
    + "    " * 9
    + "total = a + b\n    return total\n"
)


def fetch_page(c) -> tuple[str, str]:
    conn = http.client.HTTPConnection("127.0.0.1", c.port, timeout=10)
    conn.request("GET", "/", headers={"Host": f"127.0.0.1:{c.port}"})
    response = conn.getresponse()
    csp = response.getheader("Content-Security-Policy") or ""
    html = response.read().decode()
    conn.close()
    return html, csp


def sha(text: str) -> str:
    return (
        "'sha256-"
        + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
        + "'"
    )


def test_page_has_editor_score_panel_and_controls(client) -> None:  # noqa: F811
    html, _ = fetch_page(client)
    for marker in (
        '<textarea id="code"',
        'id="score"',
        'id="categories"',
        'id="save"',
        'id="rescore"',
        'id="reset"',
        'id="problem"',
        'id="language"',
        'id="statement"',
        'id="notice"',
        'id="status"',
    ):
        assert marker in html
    assert f'data-token="{client.server.token}"' in html


def test_csp_hashes_match_inline_script_and_style(client) -> None:  # noqa: F811
    html, csp = fetch_page(client)
    script_match = re.search(r"<script>(.*)</script>", html, re.DOTALL)
    style_match = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    assert script_match and style_match
    inline_script = script_match.group(1)
    inline_style = style_match.group(1)
    assert f"script-src {sha(inline_script)}" in csp
    assert f"style-src {sha(inline_style)}" in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert "default-src 'none'" in csp
    assert html.count("<script") == 1
    assert not re.search(r"\son\w+=", html)


def test_served_on_loopback_only(data) -> None:  # noqa: F811
    server, _ = serving(data)
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.url.startswith("http://127.0.0.1:")
    finally:
        server.shutdown()
        server.server_close()


def test_page_script_uses_only_api_the_server_serves() -> None:
    paths = set(re.findall(r'"(/api/[a-z]+)', page.SCRIPT))
    assert paths == {
        "/api/problems",
        "/api/baseline",
        "/api/score",
        "/api/save",
        "/api/reset",
    }
    assert "innerHTML" not in page.SCRIPT


@MISSING
def test_edit_rescore_save_then_overlay_loads_as_custom(client, data, tmp_path) -> None:  # noqa: F811
    status, text = client.call("GET", "/api/problems")
    assert status == 200
    problem = json.loads(text)["problems"][0]
    status, text = client.call(
        "GET", f"/api/baseline?problem={problem}&language=python"
    )
    baseline = json.loads(text)
    assert status == 200
    assert baseline["custom"] is False
    _, edited = client.post("/api/score", req(PASSING_NESTED, problem))
    assert edited["score"] != baseline["score"]
    assert edited["tests_passed"] is True
    status, saved = client.post("/api/save", req(GOOD, problem))
    assert status == 200
    assert Path(saved["saved"]) == tmp_path / "config/quality/overlay-python.toml"
    overlay = ov.read_overlay(
        Path(saved["saved"]).read_text(), svc.load_calibration(data.calibration_path)
    )
    assert overlay.source == "custom"
    _, text = client.call("GET", f"/api/baseline?problem={problem}&language=python")
    assert json.loads(text)["custom"] is True


@MISSING
def test_no_raw_metric_in_page_or_default_output(client) -> None:  # noqa: F811
    html, _ = fetch_page(client)
    _, body = client.call("POST", "/api/score", req(NESTED))
    view = json.loads(body)
    assert "debug" not in view
    for name in RAW_NAMES:
        assert name not in html
        assert name not in body
    assert all(0 <= c["points_lost"] <= 100 for c in view["categories"])
