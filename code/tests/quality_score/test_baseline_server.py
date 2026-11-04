import http.client
import json
import shutil
import threading
from pathlib import Path

import pytest
from varde_code.quality_score import baseline_tests as bt
from varde_code.quality_score.calibration import overlay as ov
from varde_code.quality_score.cli import baseline_service as svc
from varde_code.quality_score.cli.baseline_server import (
    BaselineServer,
    is_json_type,
    parse_code_request,
)

FIXTURE = Path(__file__).parent / "baseline_fixture"
CAL1 = Path(ov.__file__).parent / "cal-1.toml"
RAW_NAMES = (
    "debt",
    "numerator",
    "denominator",
    "per_1k",
    "breakdown",
    "worst_offenders",
)
GOOD = "def add(a, b):\n    return a + b\n"
NESTED = (
    "def add(a, b):\n"
    + "".join("    " * (i + 1) + f"if a > {i}:\n" for i in range(8))
    + "    " * 9
    + "return a + b\n    return 0\n"
)
BROKEN = "def add(a, b):\n    return a - b\n"
MISSING = pytest.mark.skipif(
    not svc.toolchain_available("python"), reason="python3 missing"
)


@pytest.fixture
def data(tmp_path, monkeypatch) -> svc.BaselineData:
    root = tmp_path / "data"
    shutil.copytree(FIXTURE, root)
    shutil.copy(CAL1, root / "cal-1.toml")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    return svc.BaselineData(root)


class Client:
    def __init__(self, server: BaselineServer) -> None:
        self.server = server
        self.port = server.server_port

    def call(self, method, path, body=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        origin = f"http://127.0.0.1:{self.port}"
        sent = {
            "Host": f"127.0.0.1:{self.port}",
            "Origin": origin,
            "Content-Type": "application/json",
            "X-Varde-Token": self.server.token,
        } | (headers or {})
        sent = {k: v for k, v in sent.items() if v is not None}
        payload = (
            raw if raw is not None else (json.dumps(body) if body is not None else None)
        )
        conn.request(method, path, body=payload, headers=sent)
        response = conn.getresponse()
        text = response.read().decode()
        conn.close()
        return response.status, text

    def post(self, path, body, **kw):
        status, text = self.call("POST", path, body, **kw)
        return status, json.loads(text)


def serving(data, debug=False):
    server = BaselineServer(data, 0, debug)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, Client(server)


@pytest.fixture
def client(data):
    server, c = serving(data)
    yield c
    server.shutdown()
    server.server_close()


def req(code, problem="adder"):
    return {"problem": problem, "language": "python", "code": code}


def numbers(value):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from numbers(item)
    elif isinstance(value, list):
        for item in value:
            yield from numbers(item)


def score_numbers(view):
    yield from [view["score"]] if view["score"] is not None else []
    yield from (c["points_lost"] for c in view["categories"])


def test_pure_helpers() -> None:
    assert is_json_type("application/json; charset=utf-8")
    assert not is_json_type("text/plain")
    assert (
        parse_code_request(b'{"problem":"a","language":"b","code":"c"}')["code"] == "c"
    )
    with pytest.raises(ValueError):
        parse_code_request(b'{"problem":1,"language":"b","code":"c"}')
    with pytest.raises(ValueError):
        parse_code_request(b"[1]")


def test_problems_and_baseline(client) -> None:
    status, text = client.call("GET", "/api/problems")
    info = json.loads(text)
    assert status == 200
    assert info["problems"] == ["adder"]
    assert info["statements"]["adder"] == "Add numbers."
    status, text = client.call("GET", "/api/baseline?problem=adder&language=python")
    view = json.loads(text)
    assert status == 200
    assert view["code"] == GOOD
    assert 0 <= view["score"] <= 100
    assert client.call("GET", "/api/baseline?problem=nope&language=python")[0] == 404


@MISSING
def test_edited_code_rescores_differently_and_numbers_stay_0_100(client) -> None:
    _, good = client.post("/api/score", req(GOOD))
    _, bad = client.post("/api/score", req(NESTED))
    assert good["score"] != bad["score"]
    assert good["tests_passed"] is True
    for view in (good, bad):
        assert all(0 <= n <= 100 for n in score_numbers(view))


@MISSING
def test_raw_fields_only_with_debug(data) -> None:
    calibration, _ = svc.effective(data, "python")
    raw = svc.score_code(NESTED, "python", calibration, None, True)["debug"]
    debt = str(raw["debt"])
    assert len(debt) > 3
    plain, c1 = serving(data)
    debugging, c2 = serving(data, debug=True)
    try:
        _, page = c1.call("GET", "/")
        _, body = c1.call("POST", "/api/score", req(NESTED))
        for name in (*RAW_NAMES, debt):
            assert name not in page
            assert name not in body
        _, debug_page = c2.call("GET", "/")
        _, debug_body = c2.call("POST", "/api/score", req(NESTED))
        assert 'id="debug"' in debug_page
        assert debt in debug_body
    finally:
        for server in (plain, debugging):
            server.shutdown()
            server.server_close()


@MISSING
def test_failing_tests_score_but_save_is_422_and_writes_nothing(
    client, tmp_path
) -> None:
    status, view = client.post("/api/score", req(BROKEN))
    assert status == 200
    assert view["tests_passed"] is False
    assert view["notice"]
    status, _ = client.post("/api/save", req(BROKEN))
    assert status == 422
    assert not (tmp_path / "config").exists()


@MISSING
def test_save_writes_overlay_and_reset_removes_it(client, data, tmp_path) -> None:
    status, saved = client.post("/api/save", req(GOOD))
    assert status == 200
    path = Path(saved["saved"])
    assert path == tmp_path / "config/quality/overlay-python.toml"
    overlay = ov.read_overlay(
        path.read_text(), svc.load_calibration(data.calibration_path)
    )
    assert overlay.source == "custom"
    assert overlay.samples[0].problem == "adder"
    sample = path.parent / "overlay-python.samples" / overlay.samples[0].code_path
    assert sample.read_text() == GOOD
    status, reset = client.post("/api/reset", {"language": "python"})
    assert (status, reset["removed"]) == (200, True)
    assert not path.exists()


def test_missing_toolchain_is_424(client, monkeypatch) -> None:
    monkeypatch.setattr(bt, "toolchain_available", lambda language: False)
    monkeypatch.setattr(svc, "toolchain_available", lambda language: False)
    status, _ = client.post("/api/save", req(GOOD))
    assert status == 424
    status, view = client.post("/api/score", req(GOOD))
    assert status == 200
    assert view["tests_passed"] is None
    assert view["notice"]


def test_oversized_code_is_413(client) -> None:
    big = "x = 1\n" * (svc.MAX_CODE_BYTES // 6 + 10)
    assert client.post("/api/score", req(big))[0] == 413
    assert client.post("/api/save", req(big))[0] == 413


def test_non_loopback_and_missing_token_refused(client) -> None:
    assert client.call("GET", "/", headers={"Host": "evil.example"})[0] == 403
    assert (
        client.call(
            "POST", "/api/score", req(GOOD), headers={"Host": "evil.example:1"}
        )[0]
        == 403
    )
    assert (
        client.call(
            "POST", "/api/score", req(GOOD), headers={"Origin": "http://evil.example"}
        )[0]
        == 403
    )
    assert (
        client.call("POST", "/api/score", req(GOOD), headers={"Origin": None})[0] == 403
    )
    assert (
        client.call("POST", "/api/score", req(GOOD), headers={"X-Varde-Token": None})[0]
        == 403
    )
    assert (
        client.call(
            "POST", "/api/score", req(GOOD), headers={"X-Varde-Token": "wrong"}
        )[0]
        == 403
    )
    assert (
        client.call(
            "POST", "/api/score", req(GOOD), headers={"Content-Type": "text/plain"}
        )[0]
        == 415
    )
    assert client.call("POST", "/api/score", raw="[1]")[0] == 400


def test_page_csp_allows_only_its_hashes(client) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", client.port, timeout=10)
    conn.request("GET", "/", headers={"Host": f"127.0.0.1:{client.port}"})
    response = conn.getresponse()
    csp = response.getheader("Content-Security-Policy")
    response.read()
    assert csp is not None
    assert "unsafe-inline" not in csp
    assert "script-src 'sha256-" in csp
