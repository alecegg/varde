import sys

from varde_runner.service.probe import probe_paths


def test_probe_paths_reports_open_success_and_error(tmp_path):
    readable = tmp_path / "readable"
    readable.write_text("content")

    result = probe_paths([str(readable), str(tmp_path / "missing")], 2)

    assert result == {str(readable): "ok", str(tmp_path / "missing"): "error"}


def test_probe_paths_reports_timeout_for_blocked_child(tmp_path):
    command = [sys.executable, "-c", "import time; time.sleep(10)"]

    result = probe_paths([str(tmp_path)], 0.05, child_command=command)

    assert result == {str(tmp_path): "timeout"}
