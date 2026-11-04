from pathlib import Path

import pytest
from varde_data.config_keys import read_allowed, write_allowed
from varde_data.errors import Invalid


def test_defaults_then_write_keeps_other_tables(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("# keep\n[serve]\nallow_edit = false\n")
    rows = {row["key"]: row for row in read_allowed(tmp_path)}
    assert rows["orchestration.stall_minutes"]["value"] == 60
    assert write_allowed(tmp_path, "orchestration.stall_minutes", 90) == 90
    text = (tmp_path / "config.toml").read_text()
    assert "# keep" in text
    assert "allow_edit = false" in text
    assert {r["key"]: r for r in read_allowed(tmp_path)}["orchestration.stall_minutes"][
        "value"
    ] == 90


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("serve.allow_edit", True),
        ("runner.enabled", True),
        ("serve.port", 1),
        ("orchestration.stall_minutes", 0),
        ("orchestration.stall_minutes", True),
        ("orchestration.stall_minutes", "9"),
    ],
)
def test_refuses_unlisted_or_invalid(tmp_path: Path, name: str, value: object) -> None:
    with pytest.raises(Invalid):
        write_allowed(tmp_path, name, value)
    assert not (tmp_path / "config.toml").exists()


def test_concurrent_writes_to_different_keys_are_not_lost(tmp_path: Path) -> None:
    import threading

    values = {
        "orchestration.stall_minutes": 11,
        "orchestration.wake_timeout_seconds": 12,
        "orchestration.wake_max_failures": 13,
        "memory.budget": 14,
        "memory.scope_warn": 15,
    }
    start = threading.Barrier(len(values))

    def write(name: str, value: int) -> None:
        start.wait()
        for _ in range(20):
            write_allowed(tmp_path, name, value)

    threads = [threading.Thread(target=write, args=item) for item in values.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    rows = {r["key"]: r["value"] for r in read_allowed(tmp_path)}
    assert {name: rows[name] for name in values} == values
