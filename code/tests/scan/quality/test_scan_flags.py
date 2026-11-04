"""CLI flags map to the scan JSON keys."""

from __future__ import annotations

import copy
import json

from varde_code import cli_scan


def _run(monkeypatch, capsys, tmp_path, *flags):
    seen = []
    monkeypatch.setattr(
        cli_scan,
        "scan_repo",
        lambda value, capture=None: (
            seen.append(copy.deepcopy(value)) or {"gate": {"status": "pass"}}
        ),
    )
    args = ["--json", json.dumps({"repoRoot": str(tmp_path)}), *flags]
    assert cli_scan.run(["scan", *args]) == 0
    capsys.readouterr()
    return seen[0]


def test_value_flags_set_json_keys(monkeypatch, capsys, tmp_path):
    seen = _run(
        monkeypatch,
        capsys,
        tmp_path,
        "--rules-ref",
        "origin/main",
        "--changed-since",
        "origin/dev",
    )
    assert seen["rulesRef"] == "origin/main"
    assert seen["changedSince"] == "origin/dev"


def test_bool_flags_set_json_keys(monkeypatch, capsys, tmp_path):
    seen = _run(
        monkeypatch,
        capsys,
        tmp_path,
        "--migrate-preview",
        "--allow-calibration-change",
    )
    assert seen["migratePreview"] is True
    assert seen["allowCalibrationChange"] is True


def test_no_flags_add_no_keys(monkeypatch, capsys, tmp_path):
    seen = _run(monkeypatch, capsys, tmp_path)
    assert set(seen) == {"repoRoot"}
