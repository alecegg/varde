from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.requests import Request
from varde_data.queue import open_queue
from varde_runner.config import config_path
from varde_runner.web.role_queues_route import create_role_queues_route
from varde_workflow.role_queue_budget import (
    DEFAULT_LIMITS,
    load_limits,
    runner_toml_path,
)

VALID = (
    "[queue_budget]\n"
    "provider_max = { alpha = 0.8 }\n"
    "rss_mb_max = 4096\n"
    "cpu_pct_max = 90\n"
    "processes_max = 500\n"
    "global_worker_ceiling = 12\n"
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _fresh_snapshot(working: Path) -> None:
    path = working / ".cache" / "data" / "resources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "taken_at": datetime.now(UTC).isoformat(),
                "providers": {"alpha": 0.2},
                "rss_mb": 100,
                "cpu_pct": 10,
                "processes": 20,
                "live_workers": 2,
            }
        ),
        encoding="utf-8",
    )


def _route_budget(working: Path) -> dict:
    route = create_role_queues_route(working, open_queue(working, "memory"))

    async def request() -> dict:
        response = await route.endpoint(_request())
        return json.loads(response.body)

    return asyncio.run(request())["budget"]


@pytest.mark.parametrize("config_dir", [None, "/srv/varde", "relative/conf"])
def test_path_resolvers_agree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_dir: str | None,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    if config_dir is None:
        monkeypatch.delenv("VARDE_RUNNER_CONFIG_DIR", raising=False)
        expected = tmp_path / ".config" / "varde" / "runner.toml"
    else:
        monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", config_dir)
        expected = Path(config_dir) / "runner.toml"

    assert runner_toml_path() == config_path() == expected


def test_route_and_cli_read_the_same_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "work"
    working.mkdir()
    _fresh_snapshot(working)
    _write(tmp_path / "conf" / "runner.toml", VALID)
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path / "conf"))

    limits, reason = load_limits(runner_toml_path())
    budget = _route_budget(working)

    assert reason == ""
    assert limits is not None
    assert budget["limits"] == asdict(limits)
    assert budget["decision"] == {"ok": True, "reason": "within budget"}


def test_missing_table_gives_both_the_same_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "work"
    working.mkdir()
    _fresh_snapshot(working)
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path / "empty"))

    limits, reason = load_limits(runner_toml_path())
    budget = _route_budget(working)

    assert (limits, reason) == (DEFAULT_LIMITS, "")
    assert budget["limits"] == asdict(DEFAULT_LIMITS)
    assert budget["decision"] == {"ok": True, "reason": "within budget"}


def test_invalid_table_blocks_both_and_names_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "work"
    working.mkdir()
    _fresh_snapshot(working)
    text = "\n".join(
        line for line in VALID.splitlines() if not line.startswith("cpu_pct_max")
    )
    _write(tmp_path / "conf" / "runner.toml", text + "\n")
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path / "conf"))

    limits, reason = load_limits(runner_toml_path())
    budget = _route_budget(working)

    assert limits is None
    assert "queue_budget.cpu_pct_max" in reason
    assert budget["limits"] is None
    assert budget["decision"] == {"ok": False, "reason": reason}


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/queue/roles",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 1),
        }
    )
