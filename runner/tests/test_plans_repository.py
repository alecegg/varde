from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from varde_data.version import Version
from varde_runner import plans_repository
from varde_runner.varde_cli import VardeCLI


def _working_with_plan(root: Path) -> Path:
    folder = root / "plans" / "sample"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text(
        "---\nid: sample\ntitle: Original\n---\n", encoding="utf-8"
    )
    return root


def test_concurrent_clis_share_first_repository_open(tmp_path, monkeypatch):
    working = _working_with_plan(tmp_path)
    open_data = plans_repository.open_data
    open_count = 0
    count_lock = threading.Lock()
    start = threading.Barrier(3)

    def counted_open(*args, **kwargs):
        nonlocal open_count
        with count_lock:
            open_count += 1
        time.sleep(0.03)
        return open_data(*args, **kwargs)

    monkeypatch.setattr(plans_repository, "open_data", counted_open)
    clients = [
        VardeCLI(cwd=working, env={"VARDE_WORKING_DIR": str(working)}) for _ in range(2)
    ]

    def get_repository(cli):
        start.wait()
        return cli._plans()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(get_repository, cli) for cli in clients]
        start.wait()
        repositories = [future.result() for future in futures]

    assert repositories[0] is repositories[1]
    assert open_count == 1


def test_concurrent_list_cache_miss_is_single_flight(tmp_path, monkeypatch):
    working = _working_with_plan(tmp_path)
    cli = VardeCLI(cwd=working, env={"VARDE_WORKING_DIR": str(working)})
    repository = cli._plans()
    original_list = repository.list
    calls = 0
    count_lock = threading.Lock()
    start = threading.Barrier(3)

    def counted_list(**kwargs):
        nonlocal calls
        with count_lock:
            calls += 1
        time.sleep(0.03)
        return original_list(**kwargs)

    monkeypatch.setattr(repository, "list", counted_list)
    monkeypatch.setattr(
        repository,
        "version",
        lambda: Version("stable", (time.time_ns() - 10_000_000_000,)),
    )

    def list_records():
        start.wait()
        return cli._list_plan_records(include_tasks=False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(list_records) for _ in range(2)]
        start.wait()
        records = [future.result() for future in futures]

    assert records[0] == records[1]
    assert calls == 1


def test_racy_version_reloads_after_plan_edit(tmp_path, monkeypatch):
    working = _working_with_plan(tmp_path)
    plan_path = working / "plans" / "sample" / "plan.md"
    cli = VardeCLI(
        cwd=working,
        env={
            "VARDE_WORKING_DIR": str(working),
            "VARDE_PLANS_BACKEND": "files",
        },
    )
    repository = cli._plans()
    original_list = repository.list
    calls = 0

    def counted_list(**kwargs):
        nonlocal calls
        calls += 1
        return original_list(**kwargs)

    monkeypatch.setattr(repository, "list", counted_list)
    monkeypatch.setattr(
        repository,
        "version",
        lambda: Version("same-key", (time.time_ns(),)),
    )
    assert cli.read_plan_summary("sample")["title"] == "Original"

    plan_path.write_text("---\nid: sample\ntitle: Updated\n---\n", encoding="utf-8")
    quantized_mtime_ns = time.time_ns() // 1_000_000_000 * 1_000_000_000
    os.utime(plan_path, ns=(quantized_mtime_ns, quantized_mtime_ns))

    assert cli.read_plan_summary("sample")["title"] == "Updated"
    assert calls == 2


def test_list_cache_retries_when_version_changes_during_load(tmp_path, monkeypatch):
    working = _working_with_plan(tmp_path)
    cli = VardeCLI(cwd=working, env={"VARDE_WORKING_DIR": str(working)})
    repository = cli._plans()
    versions = [0]
    loads = 0
    original_list = repository.list

    def changing_list(**kwargs):
        nonlocal loads
        loads += 1
        result = original_list(**kwargs)
        if loads == 1:
            versions[0] += 1
        return result

    monkeypatch.setattr(repository, "list", changing_list)
    monkeypatch.setattr(repository, "version", lambda: Version(versions[0]))

    records = cli._list_plan_records(include_tasks=False)

    assert records[0].fields["title"] == "Original"
    assert loads == 2


def test_list_cache_propagates_version_errors(tmp_path, monkeypatch):
    working = _working_with_plan(tmp_path)
    cli = VardeCLI(cwd=working, env={"VARDE_WORKING_DIR": str(working)})
    repository = cli._plans()

    def fail():
        raise RuntimeError("version failed")

    monkeypatch.setattr(repository, "version", fail)
    with pytest.raises(RuntimeError, match="version failed"):
        cli._list_plan_records(include_tasks=False)


def test_missing_working_directory_keeps_assigned_plan_fallback(
    tmp_path, monkeypatch, caplog
):
    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": ""})
    monkeypatch.setattr(cli, "_json", lambda *_args, timeout=30: {})

    assert cli.read_assigned_plans() == []
    assert "working directory" in caplog.text
    with pytest.raises(ValueError, match="working directory"):
        cli._plans()
