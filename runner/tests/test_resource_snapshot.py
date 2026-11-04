import json
from datetime import UTC, datetime
from types import SimpleNamespace

from varde_runner import resource_snapshot
from varde_runner.resource_snapshot import sample_resources, write_snapshot
from varde_workflow.role_queue_budget import ResourceSnapshot


def test_write_snapshot_is_atomic_and_matches_schema(tmp_path):
    snapshot = ResourceSnapshot(datetime(2026, 1, 2, tzinfo=UTC), {}, 12.5, 2.0, 40, 3)
    destination = tmp_path / "resources.json"
    write_snapshot(destination, snapshot)

    assert json.loads(destination.read_text()) == {
        "taken_at": snapshot.taken_at.isoformat(),
        "providers": {},
        "rss_mb": 12.5,
        "cpu_pct": 2.0,
        "processes": 40,
        "live_workers": 3,
    }
    assert list(tmp_path.glob(".resources.json.*")) == []
    assert destination.exists()


def test_sample_omits_missing_provider_data_and_counts_live_workers():
    snapshot, _ = sample_resources(
        [{"lifecycle": "running"}, {"lifecycle": "completed"}],
        now=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert snapshot.providers == {}
    assert snapshot.live_workers == 1
    assert snapshot.rss_mb >= 0
    assert snapshot.processes > 0


def test_macos_uses_process_cpu_delta_and_byte_rss(monkeypatch):
    monkeypatch.setattr(resource_snapshot.sys, "platform", "darwin")
    monkeypatch.setattr(
        resource_snapshot.resource,
        "getrusage",
        lambda _: SimpleNamespace(ru_utime=4.0, ru_stime=2.0, ru_maxrss=17_956_864),
    )
    monkeypatch.setattr(resource_snapshot.Path, "exists", lambda _: False)

    assert resource_snapshot._cpu_ticks() == 6_000_000
    assert resource_snapshot._cpu_percentage(2_000_000, 2.0) == 100.0
    assert resource_snapshot._rss_mb() == 17_956_864 / (1024 * 1024)
