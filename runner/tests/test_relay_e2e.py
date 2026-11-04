import asyncio
from pathlib import Path

import pytest
from varde_runner.relay_e2e import (
    agent_created_leftovers,
    fake_restart_drill,
    format_report,
    grep_e2e_leaks,
    temp_store_path,
    wait_for_predicate,
)

pytestmark = pytest.mark.slow


def test_temp_store_path_is_nested_under_randomized_inbox(tmp_path: Path) -> None:
    assert temp_store_path(tmp_path, "a1b2c3d4").parts[-4:] == (
        "_e2e-tmp-a1b2c3d4",
        "working",
        ".cache",
        "inbox",
    )


def test_agent_created_leftovers_returns_only_exact_known_artifacts(
    tmp_path: Path,
) -> None:
    expected = [
        tmp_path / ".e2e-idle.lock",
        tmp_path / "index" / "e2e-busy.json",
        tmp_path / "index" / "e2e-unknown.delivered.json",
        tmp_path / "cursors" / "e2e-sender",
    ]
    for path in expected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    (tmp_path / ".e2e-idle.lock.extra").touch()
    (tmp_path / "index" / "e2e-other.json").touch()
    assert agent_created_leftovers(tmp_path) == expected


def test_leak_grep_matches_only_this_runs_markers(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("to e2e-idle")
    (tmp_path / "two.txt").write_text("ordinary e2e-final")
    (tmp_path / "three.txt").write_text(
        "other-run-token and _e2e-tmp-old-token and xthis-run-tokenz"
    )
    assert grep_e2e_leaks(tmp_path, "this-run-token") == [str(tmp_path / "one.txt")]
    (tmp_path / "four.txt").write_text(
        "e2e-idle-suffix and not-e2e-sender and to e2e-sender."
    )
    assert grep_e2e_leaks(tmp_path, "this-run-token") == sorted(
        [str(tmp_path / "one.txt"), str(tmp_path / "four.txt")]
    )
    (tmp_path / "three.txt").write_text("_e2e-tmp-this-run-token")
    (tmp_path / "five.txt").write_text("token is this-run-token.")
    assert grep_e2e_leaks(tmp_path, "this-run-token") == sorted(
        [
            str(tmp_path / "one.txt"),
            str(tmp_path / "three.txt"),
            str(tmp_path / "four.txt"),
            str(tmp_path / "five.txt"),
        ]
    )


def test_report_includes_checks_cleanup_and_leaks() -> None:
    report = format_report({"pushed": True}, cleaned=True, leaks=[])
    assert report.splitlines() == [
        "PASS pushed",
        "PASS temp store cleaned",
        "PASS leak grep (0 files)",
    ]


def test_fake_restart_drill_covers_three_cycles_and_guards() -> None:
    checks = fake_restart_drill()
    assert checks == {
        "initial and post-restart deliveries": True,
        "graceful stop releases address": True,
        "restart takes over runner binding": True,
        "overlap supersedes old worker without unbinding new": True,
        "overlap cancellation releases address": True,
        "live non-runner holder remains after refusal": True,
        "non-runner holder released before restart drill": True,
        "no live-binding refusals": True,
    }


def test_wait_for_predicate_supports_async_and_sync_predicates() -> None:
    async def check() -> bool:
        async def async_true() -> bool:
            return True

        return await wait_for_predicate(
            async_true, timeout=0.2
        ) and await wait_for_predicate(lambda: True, timeout=0.2)

    assert asyncio.run(check())


def test_wait_for_predicate_bounds_async_predicate() -> None:
    async def check() -> bool:
        async def never_finishes() -> bool:
            await asyncio.Future()
            return True

        return await wait_for_predicate(never_finishes, timeout=0.01, interval=0.001)

    assert asyncio.run(check()) is False
