from __future__ import annotations

import json
from pathlib import Path

import pytest
from varde_learn.loop import calls_retention, cli_how_report
from varde_learn.loop.improve import promotion

FIXTURE = Path(__file__).parents[1] / "fixtures" / "improve-promotion" / "demand.json"


def report() -> dict:
    return json.loads(FIXTURE.read_text())["data"]


def test_repeated_requests_flag_the_step_and_single_request_does_not() -> None:
    found = {c.step: c for c in promotion.promote_candidates(report())}
    assert "varde-x/repeat" in found
    assert found["varde-x/repeat"].reasons == ("requested 4 times",)
    assert "varde-x/single" not in found
    assert "varde-y/quiet" not in found


def test_failures_and_friction_flag_a_step() -> None:
    found = {c.step: c for c in promotion.promote_candidates(report())}
    assert found["varde-x/failing"].reasons == ("2 failures or friction items",)


def test_thresholds_are_parameters() -> None:
    steps = {c.step for c in promotion.promote_candidates(report(), min_requests=1)}
    assert "varde-x/single" in steps


def test_read_demand_report_uses_the_demand_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    def fake_run(args: list[str], io: object) -> int:
        seen.append(args)
        print(FIXTURE.read_text(), end="", file=io.stdout)  # type: ignore[attr-defined]
        return 0

    monkeypatch.setattr(cli_how_report, "run", fake_run)
    data = promotion.read_demand_report("varde-x", "30d")
    assert seen == [["--json", "--window", "30d", "varde-x"]]
    assert data["swept_sessions"] == 5


def test_read_demand_report_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], io: object) -> int:
        print("bad store", file=io.stderr)  # type: ignore[attr-defined]
        return 2

    monkeypatch.setattr(cli_how_report, "run", fake_run)
    with pytest.raises(OSError, match="bad store"):
        promotion.read_demand_report()


def test_default_window_is_the_retention_days_or_unbounded() -> None:
    assert promotion.default_window(30) == "30d"
    assert promotion.default_window(None) is None


def test_read_demand_report_defaults_to_the_retention_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    def fake_run(args: list[str], io: object) -> int:
        seen.append(args)
        print(FIXTURE.read_text(), end="", file=io.stdout)  # type: ignore[attr-defined]
        return 0

    monkeypatch.setattr(cli_how_report, "run", fake_run)
    monkeypatch.setattr(calls_retention, "window_exceeds_retention", lambda _w: 30)
    promotion.read_demand_report()
    monkeypatch.setattr(calls_retention, "window_exceeds_retention", lambda _w: None)
    promotion.read_demand_report()
    assert seen == [["--json", "--window", "30d"], ["--json"]]
