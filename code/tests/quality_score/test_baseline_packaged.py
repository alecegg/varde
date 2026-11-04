import threading

import pytest
from varde_code.quality_score.baseline_tests import LANGUAGES, toolchain_available
from varde_code.quality_score.cli import baseline_service as svc
from varde_code.quality_score.cli.baseline_server import BaselineServer

DATA = svc.BaselineData(svc.DEFAULT_DATA)
PROBLEMS = ["job-scheduler", "notifier", "recurring-orders", "report-pipeline"]
CELLS = [(p, language) for p in PROBLEMS for language in LANGUAGES]


def test_packaged_layout() -> None:
    assert DATA.problems() == PROBLEMS
    assert DATA.calibration_path.is_file()
    for language in LANGUAGES:
        clamp = DATA.corpus(language)
        assert clamp
        assert all(clamp[m] for m in clamp)
    assert all(DATA.has(p, language) for p, language in CELLS)


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    import os

    os.environ["VARDE_CONFIG_DIR"] = str(tmp_path_factory.mktemp("config"))
    server = BaselineServer(DATA, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize(("problem", "language"), CELLS)
def test_shipped_sample_scores_within_range(served, problem, language) -> None:
    import http.client
    import json

    conn = http.client.HTTPConnection("127.0.0.1", served.server_port, timeout=60)
    path = f"/api/baseline?problem={problem}&language={language}"
    conn.request("GET", path, headers={"Host": f"127.0.0.1:{served.server_port}"})
    response = conn.getresponse()
    view = json.loads(response.read().decode())
    conn.close()
    assert response.status == 200
    assert 0 <= view["score"] <= 100
    assert view["code"] == DATA.agreed_code(problem, language)


@pytest.mark.parametrize(("problem", "language"), CELLS)
def test_shipped_sample_passes_its_tests(problem, language) -> None:
    if not toolchain_available(language):
        pytest.skip(f"{language} toolchain missing")
    code = DATA.agreed_code(problem, language)
    result = svc.run_behaviour_tests(DATA, problem, language, code)
    assert result is not None
    assert result.ok, result.output_tail
