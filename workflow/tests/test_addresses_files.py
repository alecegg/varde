from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import secrets
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from varde_data.addresses import open_addresses
from varde_data.backends.files import addresses_relay
from varde_data.backends.files.addresses_bindings import FilesAddresses
from varde_data.backends.files.slots_reader import SlotReader
from varde_data.errors import Locked
from varde_data.locking import file_lock
from varde_data.records.addresses import ReaderContext
from varde_data.records.messages import NewMessage
from varde_data.service import AddressService

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _pin_secrets(monkeypatch) -> None:
    counters = {"hex-4": 0, "hex-8": 0}

    def token_bytes(size: int) -> bytes:
        return b"\x01" * size

    def token_hex(size: int) -> str:
        key = f"hex-{size}"
        counters[key] += 1
        return f"{counters[key]:0{size * 2}x}"

    monkeypatch.setattr(secrets, "token_bytes", token_bytes)
    monkeypatch.setattr(secrets, "token_hex", token_hex)


def _lease_after_empty_state(root: str, start, results) -> None:
    addresses = open_addresses(Path(root), "files")
    start.wait(timeout=10)
    actions = addresses.lease_actions(
        ({"to": "reader", "message_ids": ["m-00000001"]},),
        "mailman-token",
        NOW,
    )
    results.put(bool(actions))


def _tree(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (
            path.read_bytes(),
            path.stat().st_mode & 0o777,
        )
        for path in root.rglob("*")
        if path.is_file() and path.name != ".lock" and not path.name.endswith(".lock")
    }


def _run_workflow(root: Path, script: str) -> None:
    workflow_src = Path(__file__).parents[2] / "workflow" / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(workflow_src), env.get("PYTHONPATH", "")))
    )
    subprocess.run(  # noqa: S603 - script is a fixed in-test differential fixture
        [sys.executable, "-c", script, str(root)],
        check=True,
        cwd=Path(__file__).parents[2],
        env=env,
        capture_output=True,
        text=True,
    )


_WORKFLOW_BINDING_SCRIPT = """
import secrets, sys
from datetime import UTC, datetime
from pathlib import Path
from varde_workflow.binding import BindingStore, clear_wake_gone, mark_wake_gone
now = datetime(2026, 1, 1, tzinfo=UTC)
counts = {4: 0, 8: 0}
secrets.token_bytes = lambda size: b"\\x01" * size
def token_hex(size):
    counts[size] += 1
    return f"{counts[size]:0{size * 2}x}"
secrets.token_hex = token_hex
root = Path(sys.argv[1])
store = BindingStore(root)
marker = store.issue("worker", now=now)
assert store.redeem(marker, "session-1", "h", "/first", now=now)
try:
    store.issue("worker", now=now.replace(second=1))
except ValueError:
    pass
else:
    raise AssertionError("live binding should require supersede")
replacement = store.issue("worker", now=now.replace(second=2), supersede=True)
assert store.redeem(replacement, "session-2", "h", "/second", now=now.replace(second=3))
assert store.refresh_current(
    "h", "session-2", "/refreshed", "paseo-next", now.replace(minute=1),
    agent_id="agent-next", runner_harness="codex", runner_endpoint="unix:///runner"
)
mark_wake_gone(root, "worker", now.replace(minute=2))
clear_wake_gone(root, "worker", now.replace(minute=2, second=1))
assert store.unbind("session-2", now.replace(minute=2, second=2))
assert not store.redeem(
    replacement, "session-3", "h", "/third", now=now.replace(minute=2, second=3)
)
"""

_WORKFLOW_SLOT_SCRIPT = """
import sys
from pathlib import Path
from varde_workflow.slots import add_alias
add_alias(Path(sys.argv[1]), "plan", "next")
"""


def _run_files_bindings(root: Path) -> None:
    addresses = open_addresses(root, "files")
    marker = addresses.issue("worker", now=NOW)
    context = ReaderContext(
        cwd="/first",
        paseo_id="paseo-agent",
        agent_id="agent-id",
        runner_harness="codex",
        runner_endpoint="unix:///runner",
    )
    assert addresses.redeem(marker, "session-1", "h", context, now=NOW)
    with pytest.raises(ValueError):
        addresses.issue("worker", now=NOW.replace(second=1))
    replacement = addresses.issue("worker", now=NOW.replace(second=2), supersede=True)
    assert addresses.redeem(
        replacement,
        "session-2",
        "h",
        ReaderContext(
            cwd="/second",
            paseo_id="paseo-agent",
            agent_id="agent-id",
            runner_harness="codex",
            runner_endpoint="unix:///runner",
        ),
        now=NOW.replace(second=3),
    )
    assert addresses.refresh_current(
        "h",
        "session-2",
        ReaderContext(
            cwd="/refreshed",
            paseo_id="paseo-next",
            agent_id="agent-next",
            runner_harness="codex",
            runner_endpoint="unix:///runner",
        ),
        NOW.replace(minute=1),
    )
    addresses.mark_wake_gone("worker", NOW.replace(minute=2))
    addresses.clear_wake_gone("worker", NOW.replace(minute=2, second=1))
    assert addresses.unbind("session-2", NOW.replace(minute=2, second=2))
    assert not addresses.redeem(
        replacement,
        "session-3",
        "h",
        ReaderContext(cwd="/third"),
        now=NOW.replace(minute=2, second=3),
    )


def test_files_binding_bytes_match_workflow_binding(
    tmp_path: Path, monkeypatch
) -> None:
    workflow_root = tmp_path / "workflow"
    files_root = tmp_path / "files"
    monkeypatch.setenv("PASEO_AGENT_ID", "paseo-agent")
    monkeypatch.setenv("VARDE_AGENT_ID", "agent-id")
    monkeypatch.setenv("VARDE_HARNESS", "codex")
    monkeypatch.setenv("VARDE_RUNNER_ENDPOINT", "unix:///runner")

    _pin_secrets(monkeypatch)
    _run_workflow(workflow_root, _WORKFLOW_BINDING_SCRIPT)
    _pin_secrets(monkeypatch)
    _run_files_bindings(files_root)

    assert _tree(files_root) == _tree(workflow_root)


def test_files_slot_bytes_match_workflow_and_preserve_unknown_keys(
    tmp_path: Path,
) -> None:
    workflow_root = tmp_path / "workflow"
    files_root = tmp_path / "files"
    for root in (workflow_root, files_root):
        slot_file = root / ".cache/inbox/slots/plan.json"
        slot_file.parent.mkdir(parents=True)
        slot_file.write_text(
            '{"slot":"plan","aliases":["old"],"current_address":"legacy",'
            '"custom":{"retained":true}}\n',
            encoding="utf-8",
        )

    _run_workflow(workflow_root, _WORKFLOW_SLOT_SCRIPT)
    open_addresses(files_root, "files").add_alias("plan", "next")

    workflow_path = workflow_root / ".cache/inbox/slots/plan.json"
    files_path = files_root / ".cache/inbox/slots/plan.json"
    assert files_path.read_bytes() == workflow_path.read_bytes()
    assert files_path.stat().st_mode & 0o777 == workflow_path.stat().st_mode & 0o777
    assert json.loads(files_path.read_text(encoding="utf-8"))["custom"] == {
        "retained": True
    }


def test_files_relay_event_bytes_match_workflow(tmp_path: Path) -> None:
    workflow_root = tmp_path / "workflow-relay"
    files_root = tmp_path / "files-relay"
    _run_workflow(
        workflow_root,
        """
from datetime import UTC, datetime
from pathlib import Path
import sys
from varde_workflow.relay_state import record
record(
    Path(sys.argv[1]), "waiting", now=datetime(2026, 1, 1, tzinfo=UTC),
    token_id="token", expect_return_by=""
)
""",
    )
    open_addresses(files_root, "files").record_event(
        "waiting", now=NOW, data={"token_id": "token", "expect_return_by": ""}
    )
    expected = workflow_root / ".cache/inbox/relay/state.json"
    actual = files_root / ".cache/inbox/relay/state.json"
    assert actual.read_bytes() == expected.read_bytes()
    assert actual.stat().st_mode & 0o777 == expected.stat().st_mode & 0o777


def test_files_replays_golden_relay_lease_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_path = Path(__file__).parent / "golden" / "relay" / "basic.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    case = next(
        case for case in fixture["cases"] if case["name"] == "wait_once_actions"
    )
    first_step, second_step, renew_step = (case["steps"][index] for index in (4, 6, 7))
    token_ids = iter(("00000016", "0000001b"))
    monkeypatch.setenv("PASEO_AGENT_ID", "paseo-fixed")
    monkeypatch.setattr(secrets, "token_hex", lambda _size: next(token_ids))

    def action_for(step: dict[str, object], action_id: str) -> dict[str, object]:
        store = cast("dict[str, Any]", step["store"])
        action_path = next(
            key
            for key in store
            if key.endswith(f"/actions/{action_id}.json")  # type: ignore[union-attr]
        )
        row = json.loads(store[action_path]["bytes"])
        return {
            key: row[key]
            for key in (
                "to",
                "address",
                "tier",
                "message_ids",
                "wake",
                "require_idle",
                "prompt",
                "urgent",
            )
        }

    def assert_relay_store(step: dict[str, object], root: Path) -> None:
        store = cast("dict[str, Any]", step["store"])
        expected = {
            key: (row["bytes"].encode(), int(row["mode"], 8))
            for key, row in store.items()
            if key.startswith(".cache/inbox/relay/")
        }
        actual_root = root / ".cache/inbox/relay"
        actual = {
            path.relative_to(root).as_posix(): (
                path.read_bytes(),
                path.stat().st_mode & 0o777,
            )
            for path in actual_root.rglob("*")
            if path.is_file()
        }
        assert actual == expected

    addresses = open_addresses(tmp_path, "files")
    started = NOW.replace(year=2026, month=10, day=22, hour=12)
    token_id = "00000002"  # noqa: S105 - fixed fixture mailman token.
    instance = f"{os.environ['PASEO_AGENT_ID']}:12345"
    deadline = started + timedelta(seconds=2)
    addresses.heartbeat(
        token_id, "waiting", started, instance_id=instance, expect_return_by=deadline
    )
    first_action = addresses.lease_actions(
        (action_for(first_step, "00000016"),), token_id, started
    )[0]
    assert first_action.action_id == "00000016"
    addresses.return_mailman(
        token_id,
        started,
        deadline,
        instance_id=instance,
        completed=True,
        reached_deadline=False,
    )
    assert_relay_store(first_step, tmp_path)

    second_action = addresses.lease_actions(
        (action_for(second_step, "0000001b"),),
        token_id,
        started + timedelta(seconds=1),
    )[0]
    assert second_action.action_id == "0000001b"
    assert_relay_store(second_step, tmp_path)

    assert addresses.renew(second_action.action_id, started + timedelta(seconds=2))
    assert_relay_store(renew_step, tmp_path)


def test_relay_lock_timeout_and_mode_match_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relay_root = tmp_path / ".cache/inbox/relay"
    lock_path = relay_root / ".lock"
    original = addresses_relay.file_lock

    def short_lock(path: Path, *, timeout: float):
        return original(path, timeout=min(timeout, 0.05))

    monkeypatch.setattr(addresses_relay, "file_lock", short_lock)
    repository = open_addresses(tmp_path, "files")
    repository.record_event("waiting", now=NOW, data={"token_id": "t"})
    assert lock_path.stat().st_mode & 0o777 == 0o644
    with file_lock(lock_path, timeout=1), pytest.raises(Locked):
        repository.record_event("waiting", now=NOW, data={"token_id": "t"})


def test_lease_does_not_touch_relay_wake(tmp_path: Path) -> None:
    repository = open_addresses(tmp_path, "files")
    repository.lease_actions(({"to": "reader", "message_ids": ["m"]},), "t", NOW)
    assert not (tmp_path / ".cache/inbox/relay/relay.wake").exists()


def test_relay_write_preserves_unrecognized_event_rows(tmp_path: Path) -> None:
    state_path = tmp_path / ".cache/inbox/relay/state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        '{"events":[{"event":"legacy"},"future-row",null],"cycles":{}}',
        encoding="utf-8",
    )
    open_addresses(tmp_path, "files").record_event("waiting", now=NOW)
    events = json.loads(state_path.read_text(encoding="utf-8"))["events"]
    assert events[:3] == [{"event": "legacy"}, "future-row", None]


def test_relay_heartbeat_does_not_read_archived_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    action_root = tmp_path / ".cache/inbox/relay/actions"
    action_root.mkdir(parents=True)
    archived = action_root / "old.json"
    archived.write_text("{}", encoding="utf-8")
    read = addresses_relay._read

    def guarded_read(path: Path):
        assert path != archived
        return read(path)

    monkeypatch.setattr(addresses_relay, "_read", guarded_read)
    open_addresses(tmp_path, "files").heartbeat(
        "token", "waiting", NOW, instance_id="agent"
    )


def test_begin_confirm_leaves_state_lease_status_leased(tmp_path: Path) -> None:
    repository = open_addresses(tmp_path, "files")
    action = repository.lease_actions(
        ({"to": "reader", "message_ids": ["m"]},), "t", NOW
    )[0]
    state_path = tmp_path / ".cache/inbox/relay/state.json"
    before = json.loads(state_path.read_text(encoding="utf-8"))
    result = repository.begin_confirm(action.action_id, "pushed", NOW)
    after = json.loads(state_path.read_text(encoding="utf-8"))
    assert result.status.value == "begun"
    assert after == before
    action_path = tmp_path / ".cache/inbox/relay/actions" / f"{action.action_id}.json"
    assert json.loads(action_path.read_text(encoding="utf-8"))["status"] == "confirming"


def test_slot_reader_does_not_load_bindings_or_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from varde_data.backends.files import addresses_bindings

    monkeypatch.setattr(
        addresses_bindings,
        "read_complete_lines",
        lambda _path: (_ for _ in ()).throw(AssertionError("loaded event log")),
    )
    reader = SlotReader(tmp_path)
    assert reader.resolve("plan") == "plan"
    assert reader.addresses("plan") == {"plan"}


def test_slot_snapshot_resolves_aliases_from_its_index() -> None:
    from varde_data.backends.files.slots_reader import SlotSnapshot

    snapshot = SlotSnapshot({"a-slot": ("first", "shared"), "b-slot": ("shared",)})

    assert snapshot.resolve("first") == "a-slot"
    assert snapshot.resolve("shared") == "a-slot"
    assert snapshot.resolve("b-slot") == "b-slot"
    assert snapshot.addresses("first") == {"a-slot", "first", "shared"}


def test_address_version_is_stat_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    addresses = open_addresses(tmp_path, "files")
    monkeypatch.setattr(
        addresses,
        "_load",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("loaded address state")
        ),
    )
    addresses.version()


def test_address_version_tracks_token_directory_without_globbing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    addresses = open_addresses(tmp_path, "files")
    token_dir = tmp_path / ".cache" / "inbox" / "addresses" / "worker" / "tokens"
    token_dir.mkdir(parents=True)
    token = token_dir / "token.json"
    token.write_text("old", encoding="utf-8")
    before = addresses.version()

    def fail_glob(*_args, **_kwargs):
        raise AssertionError("version enumerated address files")

    monkeypatch.setattr(Path, "glob", fail_glob)
    replacement = token.with_suffix(".tmp")
    replacement.write_text("new", encoding="utf-8")
    replacement.replace(token)

    assert addresses.version() != before


def test_files_binding_load_accepts_legacy_record_without_bound_at(
    tmp_path: Path,
) -> None:
    addresses = open_addresses(tmp_path, "files")
    inbox = tmp_path / ".cache" / "inbox"
    key = "claude-legacy"
    binding_root = inbox / "bindings"
    current_path = inbox / "addresses" / "worker" / "current"
    binding_root.mkdir(parents=True)
    current_path.parent.mkdir(parents=True)
    (binding_root / f"{key}.json").write_text(
        json.dumps(
            {
                "address": "worker",
                "harness": "claude",
                "session_id": "legacy",
                "token_id": "token-1",
                "last_seen": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    current_path.write_text(
        json.dumps({"session_key": key, "token_id": "token-1"}), encoding="utf-8"
    )

    bindings = addresses.list_bindings()

    assert len(bindings) == 1
    assert bindings[0].address == "worker"
    assert bindings[0].bound_at == NOW
    assert bindings[0].last_seen == NOW


def test_files_current_token_reads_legacy_pointer_without_binding(
    tmp_path: Path,
) -> None:
    addresses = open_addresses(tmp_path, "files")
    pointer = tmp_path / ".cache/inbox/addresses/mailman/current"
    pointer.parent.mkdir(parents=True)
    pointer.write_text('{"token_id":"legacy-mailman-token"}', encoding="utf-8")

    assert addresses.current_token("mailman") == "legacy-mailman-token"
    assert addresses.superseded("legacy-mailman-token") is False
    assert addresses.superseded("other-token") is True


def test_files_action_reads_legacy_confirm_record_without_timestamps(
    tmp_path: Path,
) -> None:
    action_dir = tmp_path / ".cache/inbox/relay/actions"
    action_dir.mkdir(parents=True)
    (action_dir / "action-legacy.json").write_text(
        json.dumps(
            {
                "action_id": "action-legacy",
                "status": "leased",
                "message_ids": ["m-legacy"],
                "address": "worker",
            }
        ),
        encoding="utf-8",
    )

    addresses = open_addresses(tmp_path, "files")
    action = addresses.action("action-legacy")
    confirmation = addresses.begin_confirm("action-legacy", "pushed", NOW)

    assert action is not None
    assert action.address == "worker"
    assert action.message_ids == ("m-legacy",)
    assert action.status == "leased"
    assert action.created_at == datetime.min.replace(tzinfo=UTC)
    assert action.expires_at == datetime.max.replace(tzinfo=UTC)
    assert confirmation.status.value == "begun"


def test_files_renew_updates_legacy_action_without_lease_row(tmp_path: Path) -> None:
    action_dir = tmp_path / ".cache/inbox/relay/actions"
    action_dir.mkdir(parents=True)
    (action_dir / "action-legacy.json").write_text(
        json.dumps(
            {
                "action_id": "action-legacy",
                "status": "leased",
                "expires_at": (NOW - timedelta(minutes=1)).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    addresses = open_addresses(tmp_path, "files")

    assert addresses.renew("action-legacy", NOW)
    action = addresses.action("action-legacy")
    assert action is not None
    assert action.expires_at == NOW + timedelta(minutes=5)


def test_shared_files_repository_is_safe_for_threaded_reads_and_writes(
    tmp_path: Path,
) -> None:
    addresses = open_addresses(tmp_path, "files")

    def read_repeatedly() -> None:
        for _ in range(40):
            addresses.list_bindings()
            addresses.slots()
            addresses.version()

    def write_bindings() -> None:
        for index in range(20):
            address = f"worker-{index}"
            marker = addresses.issue(address, now=NOW)
            assert addresses.redeem(
                marker, f"session-{index}", "h", ReaderContext(), now=NOW
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        readers = [pool.submit(read_repeatedly) for _ in range(3)]
        writer = pool.submit(write_bindings)
        for future in [*readers, writer]:
            future.result(timeout=30)

    assert len(addresses.list_bindings()) == 20


def test_write_preserves_unrelated_legacy_changes_and_unknown_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    addresses = FilesAddresses(tmp_path)
    marker = addresses.issue("existing", now=NOW)
    assert addresses.redeem(marker, "existing-session", "h", ReaderContext(), now=NOW)
    inbox = tmp_path / ".cache/inbox"
    key = "h-" + hashlib.sha256(b"existing-session").hexdigest()
    binding_path = inbox / "bindings" / f"{key}.json"
    token_path = inbox / "addresses/existing/tokens/legacy.json"
    token_path.write_text('{"unparsed":"preserve"}', encoding="utf-8")

    persist = addresses._persist

    def legacy_write_then_persist(name, state, before) -> None:
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        binding["legacy_writer_change"] = "newer"
        binding_path.write_text(
            json.dumps(binding, separators=(",", ":")), encoding="utf-8"
        )
        persist(name, state, before)

    monkeypatch.setattr(addresses, "_persist", legacy_write_then_persist)
    addresses.issue("other", now=NOW)

    assert (
        json.loads(binding_path.read_text(encoding="utf-8"))["legacy_writer_change"]
        == "newer"
    )
    assert token_path.read_text(encoding="utf-8") == '{"unparsed":"preserve"}'


def test_binding_formats_and_event_log_are_legacy_compatible(tmp_path: Path) -> None:
    addresses = open_addresses(tmp_path, "files")
    marker = addresses.issue("reader", now=NOW)
    assert addresses.redeem(marker, "session", "h", ReaderContext(cwd="/work"), now=NOW)

    inbox = tmp_path / ".cache/inbox"
    key = "h-" + hashlib.sha256(b"session").hexdigest()
    address_dir = inbox / "addresses/reader"
    current = json.loads((address_dir / "current").read_text(encoding="utf-8"))
    binding = json.loads(
        (inbox / "bindings" / f"{key}.json").read_text(encoding="utf-8")
    )
    token = next((address_dir / "tokens").glob("*.json"))
    token_record = json.loads(token.read_text(encoding="utf-8"))
    assert current == {"session_key": key, "token_id": token.stem}
    assert binding["address"] == "reader"
    assert binding["token_id"] == token.stem
    assert binding["cwd"] == "/work"
    assert token_record["sha256"]
    assert os.stat(address_dir / "current").st_mode & 0o777 == 0o600
    lines = (inbox / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["bind"]


def test_hook_refresh_preserves_runner_wake_context(tmp_path: Path) -> None:
    addresses = open_addresses(tmp_path, "files")
    hook_marker = addresses.issue("hook-first", now=NOW)
    hook_context = ReaderContext(
        cwd="/workspace",
        paseo_id="ambient-paseo-id",
        agent_id="/workspace",
        runner_harness="claude_cli",
    )
    runner_context = ReaderContext(
        cwd="/workspace",
        paseo_id="ambient-paseo-id",
        agent_id="runner-agent-id",
        runner_harness="claude_cli",
        runner_binding=True,
    )

    assert addresses.redeem(
        hook_marker, "provider-session", "claude", hook_context, now=NOW
    )
    assert addresses.redeem(
        hook_marker,
        "provider-session",
        "claude",
        runner_context,
        now=NOW + timedelta(milliseconds=1),
    )
    hook_first_binding = addresses.current_binding("hook-first")
    assert hook_first_binding is not None
    assert hook_first_binding.extra["wake_context"] == {
        "harness": "claude_cli",
        "session_id": "provider-session",
        "cwd": "/workspace",
        "agent_id": "runner-agent-id",
    }

    marker = addresses.issue("reader", now=NOW)

    assert addresses.redeem(
        marker, "provider-session", "claude", runner_context, now=NOW
    )
    assert (
        addresses.resolve_reader(
            "claude",
            "provider-session",
            marker,
            ReaderContext(
                cwd="/hook-cwd",
                paseo_id="ambient-paseo-id",
                agent_id="/workspace",
                runner_harness="claude_cli",
            ),
            NOW + timedelta(seconds=1),
        )
        == "reader"
    )

    binding = addresses.current_binding("reader")
    assert binding is not None
    wake_context = binding.extra["wake_context"]
    assert isinstance(wake_context, dict)
    assert wake_context == {
        "harness": "claude_cli",
        "session_id": "provider-session",
        "cwd": "/workspace",
        "agent_id": "runner-agent-id",
    }


def test_event_append_repairs_a_torn_tail(tmp_path: Path) -> None:
    inbox = tmp_path / ".cache/inbox"
    inbox.mkdir(parents=True)
    (inbox / "events.jsonl").write_bytes(b'{"event":"old"')
    addresses = open_addresses(tmp_path, "files")
    assert not addresses.redeem(
        "[varde-address: reader vt1.AAAAAAAAAAAAAAAAAAAAAAAAAA]",
        "session",
        "h",
        ReaderContext(),
        now=NOW,
    )
    assert (inbox / "events.jsonl").read_bytes() == (
        b'{"event":"old"\n{"event":"refuse","at":"2026-01-01T00:00:00Z",'
        b'"address":"reader","reason":"invalid-token"}\n'
    )


def test_alias_service_seeds_reader_before_publishing_alias(tmp_path: Path) -> None:
    addresses = open_addresses(tmp_path, "files")
    from varde_data.backends.files.messages import FilesMessages

    messages = FilesMessages(tmp_path)
    sent = messages.append(NewMessage("sender", "plan", "info", "backlog"))

    class CheckOrderMessages:
        def register_reader(self, reader: str, from_start: bool) -> None:
            messages.register_reader(reader, from_start)
            assert reader == "slot"
            assert from_start is True
            assert addresses.resolve_alias("plan") == "plan"
            assert messages.claim_unread(reader, "session", "hook") == ()

    AddressService(addresses, CheckOrderMessages()).add_alias("slot", "plan")  # type: ignore[arg-type]
    assert addresses.resolve_alias("plan") == "slot"
    claimed = messages.claim_unread("slot", "session", "hook")
    assert [message.id for message in claimed] == [sent.id]
    index = tmp_path / ".cache/inbox/index/slot.json"
    assert json.loads(index.read_text(encoding="utf-8"))["watermark"] > 0


def test_files_mailman_liveness_and_wake_gone(tmp_path: Path) -> None:
    addresses = open_addresses(tmp_path, "files")
    addresses.heartbeat("mail-token", "waiting", NOW, instance_id="instance")
    assert addresses.mailman_alive("mail-token", NOW + timedelta(seconds=30))
    marker = addresses.issue("worker", now=NOW)
    assert addresses.redeem(marker, "session", "h", ReaderContext(), now=NOW)
    addresses.mark_wake_gone("worker", NOW + timedelta(seconds=1))
    binding = addresses.current_binding("worker")
    assert binding is not None
    assert binding.extra["wake"] == "gone"


def test_files_address_names_include_empty_address_directory(tmp_path: Path) -> None:
    address_dir = tmp_path / ".cache/inbox/addresses/empty-address"
    address_dir.mkdir(parents=True)

    assert open_addresses(tmp_path, "files").address_names() == {"empty-address"}


def test_files_retired_legacy_sets_survive_repository_retire(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / ".cache/inbox/relay/state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        '{"retired_addresses":["legacy-address"],"retired_tokens":["legacy-token"]}',
        encoding="utf-8",
    )
    addresses = open_addresses(tmp_path, "files")

    assert addresses.retired().addresses == {"legacy-address"}
    assert addresses.retired().tokens == {"legacy-token"}
    addresses.retire(("new-address",), ("new-token",), NOW)

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["retired_addresses"] == ["legacy-address"]
    assert persisted["retired_tokens"] == ["legacy-token"]
    assert persisted["retired"] == {
        "new-address": "2026-01-01T00:00:00Z",
        "mailman:new-token": "2026-01-01T00:00:00Z",
    }
    assert addresses.retired().addresses == {"legacy-address", "new-address"}
    assert addresses.retired().tokens == {"legacy-token", "new-token"}
    assert addresses.retired_records() == {
        "new-address": "2026-01-01T00:00:00Z",
        "mailman:new-token": "2026-01-01T00:00:00Z",
    }


def test_files_relay_snapshot_includes_mailman_start_and_events(tmp_path: Path) -> None:
    addresses = open_addresses(tmp_path, "files")
    started = NOW
    addresses.heartbeat(
        "mailman-token",
        "waiting",
        started,
        instance_id="paseo-fixed:12345",
        expect_return_by=started + timedelta(seconds=30),
    )

    snapshot = addresses.relay_snapshot()

    assert snapshot.mailman_started == {"mailman-token": started}
    assert snapshot.events == (
        {
            "event": "waiting",
            "token_id": "mailman-token",
            "at": started.isoformat().replace("+00:00", "Z"),
            "expect_return_by": (started + timedelta(seconds=30))
            .isoformat()
            .replace("+00:00", "Z"),
        },
    )


def test_empty_files_lease_actions_write_workflow_state_shape(tmp_path: Path) -> None:
    addresses = open_addresses(tmp_path, "files")

    assert addresses.lease_actions((), "mailman-token", NOW) == ()

    state = tmp_path / ".cache/inbox/relay/state.json"
    assert state.read_bytes() == b'{"leases":[]}'
    assert state.stat().st_mode & 0o777 == 0o644


def test_busy_empty_lease_attempt_preserves_active_file_lease(tmp_path: Path) -> None:
    addresses = open_addresses(tmp_path, "files")
    first = addresses.lease_actions(
        ({"to": "reader", "message_ids": ["m-00000001"]},), "first", NOW
    )

    assert len(first) == 1
    assert (
        addresses.lease_actions(
            ({"to": "reader", "message_ids": ["m-00000001"]},), "second", NOW
        )
        == ()
    )

    snapshot = addresses.relay_snapshot()
    assert [action.action_id for action in snapshot.leases] == [first[0].action_id]
    state = tmp_path / ".cache/inbox/relay/state.json"
    assert (
        json.loads(state.read_text(encoding="utf-8"))["leases"][0]["action_id"]
        == first[0].action_id
    )


def test_cross_process_lease_after_empty_state_has_single_winner(
    tmp_path: Path,
) -> None:
    addresses = open_addresses(tmp_path, "files")
    assert addresses.lease_actions((), "mailman-token", NOW) == ()
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    workers = [
        context.Process(
            target=_lease_after_empty_state,
            args=(str(tmp_path), start, results),
        )
        for _ in range(4)
    ]
    for worker in workers:
        worker.start()
    start.set()
    winners = [results.get(timeout=15) for _ in workers]
    for worker in workers:
        worker.join(timeout=15)
        assert worker.exitcode == 0

    assert sum(winners) == 1


def test_runner_binding_records_parent_id(tmp_path: Path) -> None:
    addresses = open_addresses(tmp_path, "files")
    marker = addresses.issue("child", now=NOW)
    context = ReaderContext(
        cwd="/work",
        agent_id="child-agent",
        runner_harness="codex-app-server",
        runner_binding=True,
        parent_id="parent-agent",
    )

    assert addresses.redeem(marker, "provider-session", "codex", context, now=NOW)

    binding = addresses.current_binding("child")
    assert binding is not None
    assert binding.extra["parent_id"] == "parent-agent"
    reopened = open_addresses(tmp_path, "files").current_binding("child")
    assert reopened is not None
    assert reopened.extra["parent_id"] == "parent-agent"


def test_binding_without_parent_has_no_parent_id(tmp_path: Path) -> None:
    addresses = open_addresses(tmp_path, "files")
    marker = addresses.issue("solo", now=NOW)
    assert addresses.redeem(marker, "s", "codex", ReaderContext(cwd="/w"), now=NOW)
    binding = addresses.current_binding("solo")
    assert binding is not None
    assert "parent_id" not in binding.extra
