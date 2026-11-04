from __future__ import annotations

import json
import re

import pytest
from varde_code import cli_scan
from varde_code.scan.report_run import run_report

PASS = {
    "ok": True,
    "data": {
        "analysis": {"status": "complete"},
        "gate": {"status": "pass"},
        "findings": [],
    },
}
MISSING = {"ok": False, "data": {"error": {"code": "index_missing"}}}
STALE = {"ok": False, "data": {"error": {"code": "index_stale"}}}


class Fakes:
    def __init__(self, outputs, build_error=None):
        self.outputs = list(outputs)
        self.build_error = build_error
        self.payloads = []
        self.builds = 0

    def scan(self, payload):
        self.payloads.append(payload)
        return self.outputs.pop(0)

    def build(self, root):
        self.builds += 1
        if self.build_error:
            raise RuntimeError(self.build_error)


def report(root, outputs, no_build=False, build_error=None):
    fakes = Fakes(outputs, build_error)
    code = run_report(root, no_build, 100, scan=fakes.scan, build=fakes.build)
    return code, fakes


def test_pass_needs_no_build(tmp_path, capsys):
    code, fakes = report(tmp_path, [PASS])
    assert code == 0
    assert fakes.builds == 0
    assert re.search(r"gate=pass .* build=\d+s scan=\d+s", capsys.readouterr().out)


def test_index_missing_builds_once_then_retries(tmp_path, capsys):
    code, fakes = report(tmp_path, [MISSING, PASS])
    assert code == 0
    assert fakes.builds == 1
    assert len(fakes.payloads) == 2
    assert "gate=pass" in capsys.readouterr().out


def test_persistent_missing_index_fails_after_two_scans(tmp_path, capsys):
    code, fakes = report(tmp_path, [MISSING, MISSING])
    assert code == 1
    assert len(fakes.payloads) == 2
    assert capsys.readouterr().err


def test_build_failure_fails_with_message(tmp_path, capsys):
    code, fakes = report(tmp_path, [STALE], build_error="build failed")
    err = capsys.readouterr().err
    assert code == 1
    assert "build failed" in err
    assert "scan index build failed" in err
    assert len(fakes.payloads) == 1


def test_no_build_prints_recovery_without_retry(tmp_path, capsys):
    code, fakes = report(tmp_path, [MISSING], no_build=True)
    out = capsys.readouterr().out
    assert code == 0
    assert fakes.builds == 0
    assert len(fakes.payloads) == 1
    assert out.strip() == (
        f'status=index_missing recovery="varde map build --repo-root {tmp_path}"'
    )


@pytest.mark.parametrize(
    "output",
    [
        {"ok": False, "data": {"error": {"code": "tool_error"}}},
        {"invalid": "schema"},
        {
            "ok": True,
            "data": {
                "analysis": {"status": "incomplete"},
                "gate": {"status": "unknown"},
                "findings": [],
            },
        },
    ],
)
def test_errors_and_incomplete_analysis_fail(tmp_path, capsys, output):
    code, _ = report(tmp_path, [output])
    assert code == 1
    assert capsys.readouterr().err


def test_quoted_root_is_passed_intact(tmp_path):
    root = tmp_path / 'repo"quoted'
    root.mkdir()
    code, fakes = report(root, [PASS])
    assert code == 0
    assert json.loads(json.dumps(fakes.payloads[0])) == {"repoRoot": str(root)}


def test_bad_root_exits_two(tmp_path, capsys):
    code, fakes = report(tmp_path / "missing", [])
    assert code == 2
    assert fakes.payloads == []
    assert capsys.readouterr().err


def test_pack_warnings_only_in_varde_repo_and_never_change_exit(
    tmp_path, capsys, monkeypatch
):
    from varde_code.scan import report_run

    monkeypatch.setattr(report_run, "collect_pack_warnings", lambda *_: ["packs bad"])
    code, _ = report(tmp_path, [PASS])
    assert code == 0
    assert "packs bad" not in capsys.readouterr().err

    (tmp_path / "justfile").write_text("")
    (tmp_path / ".githooks").mkdir()
    code, _ = report(tmp_path, [PASS])
    assert code == 0
    assert "warning: packs bad" in capsys.readouterr().err


def test_cli_routes_report_flags(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli_scan.report_run,
        "run_report",
        lambda root, no_build, behind: calls.append((root, no_build, behind)) or 0,
    )
    code = cli_scan.run(
        [
            "--report",
            "--repo-root",
            str(tmp_path),
            "--no-build",
            "--readme-max-behind",
            "7",
        ]
    )
    assert code == 0
    assert calls == [(tmp_path, True, 7)]


def test_cli_rejects_unknown_report_argument(capsys):
    assert cli_scan.run(["--report", "--bogus"]) == 2
    assert "--bogus" in capsys.readouterr().err
