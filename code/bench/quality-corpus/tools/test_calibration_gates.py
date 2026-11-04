from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import calibration_gates as gates  # noqa: E402, RUF100

LEDGER_OK = (True, "ledger check exit 0")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _plan(tmp_path: Path) -> Path:
    plan = tmp_path / "calibration"
    plan.mkdir()
    return plan


def _dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "panel/notes/panel-1/dataset"
    items = [
        {"record_type": "items"},
        {"id": "u1:a", "language": "python", "split": "dev"},
        {"id": "u1:b", "language": "python", "split": "dev"},
        {"id": "u2:a", "language": "csharp", "split": "dev"},
    ]
    _write(dataset / "items.jsonl", "".join(json.dumps(r) + "\n" for r in items))
    return dataset


def test_missing_handoff_is_not_ready(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    label = {"unit_id": "u1", "a_item_id": "u1:a", "b_item_id": "u1:b"}
    _write(dataset / "labels/b1.jsonl", json.dumps(label) + "\n")

    status = gates.panel_status(tmp_path / "panel", "python", LEDGER_OK)

    assert status.ready is False  # noqa: S101 - pytest assertion.
    assert "handoff.md missing" in status.detail  # noqa: S101
    assert "dev 1 labelled" in status.detail  # noqa: S101


def test_panel_ready_needs_handoff_labels_and_ledger(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    label = {"unit_id": "u1", "a_item_id": "u1:a", "b_item_id": "u1:b"}
    _write(dataset / "labels/b1.jsonl", json.dumps(label) + "\n")
    _write(tmp_path / "panel/notes/panel-1/handoff.md", "done\n")

    assert gates.panel_status(tmp_path / "panel", "python", LEDGER_OK).ready  # noqa: S101
    csharp = gates.panel_status(tmp_path / "panel", "csharp", LEDGER_OK)
    assert csharp.ready is False and "no dev labels" in csharp.detail  # noqa: S101
    failing = gates.panel_status(tmp_path / "panel", "python", (False, "ledger bad"))
    assert failing.ready is False  # noqa: S101


def test_verdict_pass_is_ready_and_missing_verdict_records_numbers(
    tmp_path: Path,
) -> None:
    resolver = tmp_path / "resolver"
    _write(
        resolver / "notes/gaps/csharp-after.md",
        "| step | P | R |\n| --- | --- | --- |\n| final | 0.96 | 0.39 |\n"
        "- variable-receiver 45: needs-new-facts (declared types)\n",
    )
    pending = gates.resolver_status(resolver, "csharp")
    assert pending.ready is False  # noqa: S101
    assert "| final | 0.96 | 0.39 |" in pending.detail  # noqa: S101
    assert "needs-new-facts: - variable-receiver 45" in pending.detail  # noqa: S101

    _write(resolver / "notes/dev-final/verdict.md", "python: PASS\ncsharp: FAIL\n")
    assert gates.resolver_status(resolver, "python").ready  # noqa: S101
    assert gates.resolver_status(resolver, "csharp").ready is False  # noqa: S101
    _write(resolver / "notes/dev-final/verdict.md", "PASS\n")
    assert gates.resolver_status(resolver, "csharp").ready  # noqa: S101


def test_tuning_status_names_failing_margins_per_language() -> None:
    report = {
        "samples": [
            {"id": "sp", "constraints": [{"challenger": "judge", "margin": 5}]},
            {"id": "sc", "constraints": [{"challenger": "judge", "margin": 3}]},
        ],
        "loo": [{"held_out": "sc", "margins": [{"challenger": "tiny", "margin": -9}]}],
    }
    languages_of = {"sp": "python", "sc": "csharp"}

    assert gates.tuning_status(report, "python", languages_of).ready  # noqa: S101
    csharp = gates.tuning_status(report, "csharp", languages_of)
    assert csharp.ready is False and "loo sc tiny -9" in csharp.detail  # noqa: S101
    assert gates.tuning_status(None, "python", languages_of).ready is False  # noqa: S101


def test_main_reports_three_rows_and_require_exit_code(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    plan = _plan(tmp_path)
    out = plan / "notes/gates.md"
    monkeypatch.setattr(gates, "sample_languages", dict)
    monkeypatch.setattr(gates, "ledger_check", lambda ledger: (False, "no ledger"))
    base = ["calibration_gates.py", "--plan-dir", str(plan), "--out", str(out)]

    monkeypatch.setattr(sys, "argv", [*base, "--skip-tuning"])
    assert gates.main() == 0  # noqa: S101 - pytest assertion.
    text = out.read_text(encoding="utf-8")
    rows = [
        line
        for line in text.splitlines()
        if line.startswith("| ") and "NOT READY" in line
    ]
    assert len(rows) == 3  # noqa: S101

    monkeypatch.setattr(
        sys,
        "argv",
        [*base, "--skip-tuning", "--require", "panel", "--languages", "python"],
    )
    assert gates.main() == 1  # noqa: S101
    assert "NOT READY: python: panel" in capsys.readouterr().out  # noqa: S101
