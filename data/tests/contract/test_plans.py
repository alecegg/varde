from __future__ import annotations

import os
import shutil
import time
from dataclasses import replace
from pathlib import Path

import pytest
from plans_backends import open_backend
from varde_core.frontmatter import parse
from varde_data.backends.files import plans_index as plans_index_module
from varde_data.backends.files.plans import FilesPlans
from varde_data.backends.sqlite.plans import SqlitePlans
from varde_data.errors import Conflict, Invalid, Locked, NotFound
from varde_data.frontmatter_patch import patch_fields
from varde_data.locking import file_lock
from varde_data.records.plans import PlanRecord, TaskRecord
from varde_data.testing import MemoryPlans
from varde_data.version import Version


def _document(**values: str) -> bytes:
    fields = "\n".join(f"{key}: {value}" for key, value in values.items())
    return f"---\n{fields}\n---\nbody\n".encode()


def test_plan_record_typed_frontmatter_accessors() -> None:
    record = PlanRecord(
        "plan",
        {
            "status": "active",
            "title": "Example",
            "owner": "alec",
            "assigned_to": "orchestrator-1",
            "depends_on": ["first", 3, "second"],
        },
        b"",
        0,
        "plan.md",
    )

    assert record.status == "active"
    assert record.title == "Example"
    assert record.owner == "alec"
    assert record.assigned_to == "orchestrator-1"
    assert record.depends_on == ("first", "second")


def test_plan_record_typed_accessors_handle_missing_and_malformed_values() -> None:
    absent = PlanRecord("absent", {}, b"", 0, "plan.md")
    malformed = PlanRecord(
        "malformed",
        {"owner": ["alec"], "depends_on": 42},
        b"",
        0,
        "plan.md",
    )
    bare_string = PlanRecord(
        "string-dependency", {"depends_on": "prerequisite"}, b"", 0, "plan.md"
    )

    assert absent.status is None
    assert absent.title is None
    assert absent.owner is None
    assert absent.assigned_to is None
    assert absent.depends_on == ()
    assert malformed.owner is None
    assert malformed.depends_on == ()
    assert bare_string.depends_on == ("prerequisite",)


@pytest.fixture(params=("memory", "files"))
def plans(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "files":
        return FilesPlans(tmp_path)
    return MemoryPlans()


def _seed_memory(plans: MemoryPlans, root: Path) -> None:
    raw = _document(id="2026-10-23-alpha", type="plan", owner="alice", custom="keep")
    plans.records.append(
        PlanRecord(
            "2026-10-23-alpha",
            {
                "id": "2026-10-23-alpha",
                "type": "plan",
                "owner": "alice",
                "custom": "keep",
            },
            raw,
            10.0,
            str(root / "plans/2026-10-23-alpha/plan.md"),
            archived=False,
            extra={"custom": "keep"},
        )
    )


@pytest.mark.parametrize("backend", ("files", "memory", "sqlite"))
def test_read_repository_backends_match_records(backend: str, tmp_path: Path) -> None:
    active = tmp_path / "plans" / "2026-10-23-alpha"
    (active / "tasks").mkdir(parents=True)
    (active / "plan.md").write_bytes(
        b"---\nid: alpha\ntype: plan\nowner: alice\ncustom: keep\n"
        b"created: !!timestamp 2026-10-24T12:00:00Z\n---\nbody\n"
    )
    (active / "review.md").write_bytes(_document(verdict="approved"))
    (active / "tasks" / "01-work.md").write_bytes(
        _document(id="work", type="task", status="todo")
    )
    (active / "tasks" / "02-bad.md").write_bytes(b"bad task frontmatter")
    archived = tmp_path / "plans" / "archive" / "old"
    archived.mkdir(parents=True)
    (archived / "plan.md").write_bytes(_document(id="old", type="plan"))
    standalone = tmp_path / "plans" / "standalone"
    standalone.mkdir()
    (standalone / "task.md").write_bytes(_document(id="solo", type="task"))
    malformed = tmp_path / "plans" / "malformed"
    malformed.mkdir()
    (malformed / "plan.md").write_bytes(b"bad plan frontmatter")
    for directory, identifier in (
        ("2026-01-01-dup", "first"),
        ("2026-01-02-dup", "second"),
    ):
        duplicate = tmp_path / "plans" / directory
        duplicate.mkdir()
        (duplicate / "plan.md").write_bytes(_document(id=identifier, type="plan"))

    reference = FilesPlans(tmp_path)
    plans = open_backend(backend, tmp_path)
    for include_archived in (False, True):
        for include_tasks in (False, True):
            actual = plans.list(
                include_archived=include_archived, include_tasks=include_tasks
            )
            expected = reference.list(
                include_archived=include_archived, include_tasks=include_tasks
            )
            assert actual.records == expected.records
            assert actual.skipped == (0 if backend == "memory" else expected.skipped)
    assert plans.get("alpha") == reference.get("alpha")
    assert plans.get("old", include_archived=True) == reference.get(
        "old", include_archived=True
    )
    assert plans.get("solo") == reference.get("solo")
    with pytest.raises(Conflict):
        plans.get("dup")
    for path in (active / "plan.md", active / "tasks" / "01-work.md"):
        assert plans.get_by_path(str(path)) == reference.get_by_path(str(path))
    relative_plan = os.path.relpath(active / "plan.md")
    if backend != "memory":
        assert plans.get_by_path(relative_plan) == reference.get_by_path(relative_plan)
    assert plans.get_by_path(str(standalone / "task.md")) == reference.get_by_path(
        str(standalone / "task.md")
    )
    assert [record.id for record in plans.owner_lookup("alice")] == [
        record.id for record in reference.owner_lookup("alice")
    ]


def test_sqlite_reads_query_index_without_source_stats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "plans" / "alpha" / "plan.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(_document(id="alpha", type="plan", owner="alice"))
    plans = open_backend("sqlite", tmp_path)
    assert isinstance(plans, SqlitePlans)

    def fail_stat(*args, **kwargs):
        raise AssertionError("SQLite reader statted source files")

    def fail_refresh(*args, **kwargs):
        raise AssertionError("SQLite reader refreshed during a read")

    monkeypatch.setattr(Path, "stat", fail_stat)
    monkeypatch.setattr(plans, "refresh", fail_refresh)
    monkeypatch.setattr(plans._index, "refresh", fail_refresh)
    assert plans.list().records[0].id == "alpha"
    assert plans.get("alpha").id == "alpha"
    assert plans.get_by_path(str(path)).id == "alpha"
    assert plans.owner_lookup("alice")[0].id == "alpha"
    version = plans.version()
    assert isinstance(version, Version)
    assert isinstance(version.value, int)
    assert version.value > 0


def test_sqlite_writer_refreshes_for_same_handle_read_after_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "plans" / "alpha" / "plan.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(_document(id="alpha", type="plan", owner="alice"))
    plans = open_backend("sqlite", tmp_path)
    before = plans.version()
    assert isinstance(before.value, int)
    plans.set_owner(plans.get("alpha"), "bob")
    assert plans.version() == Version(before.value + 1)
    assert plans.get("alpha").owner == "bob"


def test_sqlite_refresh_tracks_invalid_documents_and_skipped_tasks(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plans" / "alpha" / "plan.md"
    task_path = plan_path.parent / "tasks" / "01-work.md"
    task_path.parent.mkdir(parents=True)
    plan_path.write_bytes(_document(id="alpha", type="plan"))
    task_path.write_bytes(b"bad task frontmatter")
    plans = open_backend("sqlite", tmp_path)
    assert isinstance(plans, SqlitePlans)
    assert plans.list().skipped == 0
    assert plans.get("alpha").skipped_tasks == 1

    task_path.write_bytes(_document(id="work", type="task"))
    plans.refresh()
    assert plans.list().skipped == 0
    assert plans.get("alpha").skipped_tasks == 0

    task_path.unlink()
    plans.refresh()
    assert plans.get("alpha").skipped_tasks == 0


def test_open_fresh_plans_rebuilds_a_deleted_index(tmp_path: Path) -> None:
    from varde_data.plans import open_fresh_plans, open_plans

    path = tmp_path / "plans" / "alpha" / "plan.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(_document(id="alpha", type="plan", owner="alice"))
    first = open_fresh_plans(tmp_path)
    expected = first.list()
    assert isinstance(open_plans(tmp_path, "sqlite"), SqlitePlans)
    assert isinstance(open_plans(tmp_path), FilesPlans)
    first._index.path.unlink()
    reopened = open_fresh_plans(tmp_path)
    assert reopened.list() == expected


def test_plan_reader_shapes_archive_standalone_and_skipped(
    plans, tmp_path: Path
) -> None:
    """Filesystem parsing/skipped counts are files-only; memory uses parsed records."""
    root = tmp_path / "plans"
    folder = root / "2026-10-23-alpha"
    (folder / "tasks").mkdir(parents=True)
    (folder / "plan.md").write_bytes(
        _document(id="2026-10-23-alpha", type="plan", owner="alice", custom="keep")
    )
    (folder / "review.md").write_bytes(_document(verdict="approved"))
    (folder / "tasks" / "01-work.md").write_bytes(
        _document(id="01-work", type="task", title="Work")
    )
    (folder / "tasks" / "02-bad.md").write_bytes(b"bad frontmatter")
    (root / "standalone").mkdir(parents=True)
    (root / "standalone" / "task.md").write_bytes(
        _document(type="task", title="Standalone")
    )
    malformed = root / "malformed"
    malformed.mkdir()
    (malformed / "plan.md").write_bytes(b"not frontmatter")
    archived = root / "archive" / "old"
    archived.mkdir(parents=True)
    (archived / "plan.md").write_bytes(_document(id="old", type="plan"))
    if isinstance(plans, MemoryPlans):
        _seed_memory(plans, tmp_path)
        # Memory records are already parsed, so filesystem parse failures do not apply.
        result = plans.list()
        assert result.skipped == 0
        assert result.records[0].extra["custom"] == "keep"
        assert plans.list(include_archived=True).records[0].archived is False
        return
    result = plans.list()
    assert result.skipped == 1
    record = next(item for item in result.records if item.id == "2026-10-23-alpha")
    assert record.raw.startswith(b"---") and record.path.endswith("plan.md")
    assert record.extra == {"custom": "keep"}
    assert record.review_verdict == "approved"
    assert record.skipped_tasks == 1
    assert [task.id for task in record.tasks] == ["01-work"]
    assert any(item.artifact_type == "task" for item in result.records)
    assert not any(item.id == "old" for item in result.records)
    assert next(
        item for item in plans.list(include_archived=True).records if item.id == "old"
    ).archived


def test_plan_list_can_skip_task_records(plans, tmp_path: Path) -> None:
    if isinstance(plans, MemoryPlans):
        _seed_memory(plans, tmp_path)
        plans.records[0] = replace(
            plans.records[0],
            tasks=(PlanRecord("task", {}, b"", 0, "task", artifact_type="task"),),
        )
        assert len(plans.list().records[0].tasks) == 1
        assert plans.list(include_tasks=False).records[0].tasks == ()
        return
    folder = tmp_path / "plans" / "active"
    (folder / "tasks").mkdir(parents=True)
    (folder / "plan.md").write_bytes(_document(id="active", type="plan"))
    (folder / "tasks" / "task.md").write_bytes(_document(type="task"))
    record = FilesPlans(tmp_path).list(include_tasks=False).records[0]
    assert record.tasks == ()


def test_plan_writer_conflicts_with_hand_edit_and_preserves_mode(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "plans" / "active"
    folder.mkdir(parents=True)
    path = folder / "plan.md"
    path.write_bytes(_document(type="plan", id="active", owner="alice"))
    path.chmod(0o640)
    repository = FilesPlans(tmp_path)
    expected = repository.get_by_path(str(path))
    changed = path.read_bytes().replace(b"owner: alice", b"owner: editor")
    path.write_bytes(changed)
    with pytest.raises(Conflict):
        repository.set_owner(expected, "bob")
    assert path.read_bytes() == changed
    assert list(folder.glob(".*.tmp")) == []
    fresh = repository.get_by_path(str(path))
    saved = repository.set_owner(fresh, "bob")
    assert saved.fields["owner"] == "bob"
    assert path.stat().st_mode & 0o777 == 0o640


def test_plan_writer_rechecks_after_staging_before_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from varde_data.backends.files import plans_write

    folder = tmp_path / "plans" / "active"
    folder.mkdir(parents=True)
    path = folder / "plan.md"
    path.write_bytes(_document(type="plan", id="active", owner="alice"))
    repository = FilesPlans(tmp_path)
    expected = repository.get_by_path(str(path))
    edited = path.read_bytes().replace(b"owner: alice", b"owner: editor")
    atomic = plans_write.atomic_write

    def stage_then_edit(target: Path, data: bytes, *, mode: int) -> None:
        atomic(target, data, mode=mode)
        path.write_bytes(edited)

    monkeypatch.setattr(plans_write, "atomic_write", stage_then_edit)
    with pytest.raises(Conflict):
        repository.set_owner(expected, "bob")
    assert path.read_bytes() == edited
    assert list(folder.glob(".*.tmp")) == []


@pytest.mark.parametrize(
    "raw",
    (
        (
            b"---\r\ntype: plan\r\nowner: old\r\n  continuation\r\n"
            b"other: keep\r\n---\r\nbody\r\n"
        ),
        b"---\ntype: plan\nowner: old\nother: keep\n---\nbody",
        b"---\n---\nbody\n",
        b"---\ntype: plan\nowner: old\n- orphan\n---\nbody\n",
        b"---\nowner: first\nowner: second\n---\nbody\n",
        b"---\ntype: plan\nowner: old\n\tcontinuation\ncustom: keep\n---\n",
        b"---\ntype: plan\nowner:\n# comment\nowner_extra: keep\n---\n",
        b"---\ntype: plan\n  owner: nested\n---\nbody",
    ),
)
def test_plan_writer_surgical_edge_corpus(raw: bytes, tmp_path: Path) -> None:
    updated = patch_fields(raw, set_fields={"owner": "new"})
    if b"\r\n" in raw:
        expected = _old_set_owner_line(raw.replace(b"\r\n", b"\n"), "new")
        assert updated.replace(b"\r\n", b"\n") == expected
    else:
        assert updated == _old_set_owner_line(raw, "new")


@pytest.mark.parametrize(
    "raw",
    (
        b"---\ntype: plan\nassigned_to: old\n  continuation\ncustom: keep\n---\n",
        b"---\ntype: plan\nassigned_to: old\nassigned_to: second\n---\nbody",
        b"---\ntype: plan\ncustom: keep\n---\nbody\n",
    ),
)
def test_assign_field_patcher_matches_old_set_and_remove(raw: bytes) -> None:
    assert patch_fields(raw, set_fields={"assigned_to": "new"}) == (
        _old_set_field_line(raw, "assigned_to", "new")
    )
    assert patch_fields(raw, remove_fields=("assigned_to",)) == (
        _old_remove_field_line(raw, "assigned_to")
    )


@pytest.mark.parametrize(
    "line",
    (
        b"merge_approved_at:\n",
        b"merge_approved_at: null\n",
        b"merge_approved_at: ''\n",
        b"merge_approved_at: >\n  old\n",
    ),
)
def test_approve_merge_does_not_overwrite_present_key_line(
    tmp_path: Path, line: bytes
) -> None:
    folder = tmp_path / "plans" / "active"
    folder.mkdir(parents=True)
    path = folder / "plan.md"
    original = b"---\ntype: plan\nid: active\n" + line + b"---\nbody\n"
    path.write_bytes(original)
    repository = FilesPlans(tmp_path)
    stored = repository.set_merge_approved_at(
        repository.get_by_path(str(path)), "2026-10-23T10:00:00Z"
    )
    assert path.read_bytes() == original
    assert stored.raw == original


@pytest.mark.parametrize(
    "value",
    ("line\u2028break", "line\u2029break", "line\u0085break", "line\x00break"),
)
def test_writer_rejects_unicode_line_breaks_as_invalid(
    tmp_path: Path, value: str
) -> None:
    folder = tmp_path / "plans" / "active"
    folder.mkdir(parents=True)
    path = folder / "plan.md"
    path.write_bytes(_document(type="plan", id="active"))
    repository = FilesPlans(tmp_path)
    with pytest.raises(Invalid, match="single-line"):
        repository.set_owner(repository.get_by_path(str(path)), value)


def test_writer_wraps_malformed_frontmatter_as_invalid(tmp_path: Path) -> None:
    folder = tmp_path / "plans" / "active"
    folder.mkdir(parents=True)
    path = folder / "plan.md"
    path.write_bytes(b"not frontmatter")
    record = PlanRecord("active", {"type": "plan"}, path.read_bytes(), 0, str(path))
    with pytest.raises(Invalid, match="frontmatter"):
        FilesPlans(tmp_path).set_owner(record, "alice")


def test_task_transition_uses_status_parsed_from_locked_bytes(tmp_path: Path) -> None:
    folder = tmp_path / "plans" / "active" / "tasks"
    folder.mkdir(parents=True)
    path = folder / "one.md"
    raw = _document(type="task", id="one", status="blocked")
    path.write_bytes(raw)
    expected = PlanRecord(
        "one",
        {"type": "task", "id": "one", "status": "todo"},
        raw,
        0,
        str(path),
        artifact_type="task",
    )
    with pytest.raises(Invalid, match="blocked"):
        FilesPlans(tmp_path).set_task_status(
            expected,
            "active",
            status_at="now",
            transitions={"todo": frozenset({"active"})},
        )


def test_task_and_plan_writer_share_plan_directory_lock(
    tmp_path: Path, monkeypatch
) -> None:
    from varde_data.backends.files import plans_write

    folder = tmp_path / "plans" / "active"
    tasks = folder / "tasks"
    tasks.mkdir(parents=True)
    plan_path = folder / "plan.md"
    task_path = tasks / "one.md"
    plan_path.write_bytes(_document(type="plan", id="active"))
    task_path.write_bytes(_document(type="task", id="one", status="todo"))
    repository = FilesPlans(tmp_path)
    lock_paths = []
    original_lock = plans_write.file_lock

    def track_lock(path: Path, *, timeout: float):
        lock_paths.append(path)
        return original_lock(path, timeout=timeout)

    monkeypatch.setattr(plans_write, "file_lock", track_lock)
    repository.set_owner(repository.get_by_path(str(plan_path)), "alice")
    repository.set_task_status(
        repository.get_by_path(str(task_path)),
        "active",
        status_at="now",
        transitions={"todo": frozenset({"active"})},
    )
    assert lock_paths == [folder / ".plan.lock", folder / ".plan.lock"]


def test_standalone_task_writer_uses_its_own_directory_lock(
    tmp_path: Path, monkeypatch
) -> None:
    from varde_data.backends.files import plans_write

    folder = tmp_path / "plans" / "standalone"
    folder.mkdir(parents=True)
    path = folder / "task.md"
    path.write_bytes(_document(type="task", id="one", status="todo"))
    repository = FilesPlans(tmp_path)
    lock_paths = []
    original_lock = plans_write.file_lock

    def track_lock(lock_path: Path, *, timeout: float):
        lock_paths.append(lock_path)
        return original_lock(lock_path, timeout=timeout)

    monkeypatch.setattr(plans_write, "file_lock", track_lock)
    repository.set_task_status(
        repository.get_by_path(str(path)),
        "active",
        status_at="now",
        transitions={"todo": frozenset({"active"})},
    )
    assert lock_paths == [folder / ".plan.lock"]


def test_replace_body_writer_matches_old_byte_replacement(tmp_path: Path) -> None:
    folder = tmp_path / "plans" / "active"
    folder.mkdir(parents=True)
    path = folder / "plan.md"
    raw = b"---\ntype: plan\nid: active\n---\nold body\n"
    path.write_bytes(raw)
    body = b"new body\nwith another line\n"
    old = raw[: -len(b"old body\n")] + body
    result = FilesPlans(tmp_path).replace_body(
        FilesPlans(tmp_path).get_by_path(str(path)), body
    )
    assert path.read_bytes() == old
    assert result.raw == old


def _old_set_owner_line(data: bytes, owner: str) -> bytes:
    return _old_set_field_line(data, "owner", owner)


def _old_set_field_line(data: bytes, key: str, value: str) -> bytes:
    start, end = _old_frontmatter_bounds(data)
    from varde_core.yamlio import dump_yaml

    rendered = dump_yaml(value).splitlines()[1]
    replacement = f"{key}: {rendered}".encode()
    line_start = start
    while line_start < end:
        line_end = data.find(b"\n", line_start, end)
        line_end = end if line_end < 0 else line_end
        if data[line_start:line_end].startswith(f"{key}:".encode()):
            remove_end = line_end + (data[line_end : line_end + 1] == b"\n")
            while remove_end < end and data[remove_end : remove_end + 1] in (
                b" ",
                b"\t",
            ):
                next_line = data.find(b"\n", remove_end, end)
                remove_end = end if next_line < 0 else next_line + 1
            return data[:line_start] + replacement + b"\n" + data[remove_end:]
        line_start = line_end + 1
    return data[:end] + replacement + b"\n" + data[end:]


def _old_remove_field_line(data: bytes, key: str) -> bytes:
    start, end = _old_frontmatter_bounds(data)
    line_start = start
    while line_start < end:
        line_end = data.find(b"\n", line_start, end)
        line_end = end if line_end < 0 else line_end
        if data[line_start:line_end].startswith(f"{key}:".encode()):
            remove_end = line_end + (data[line_end : line_end + 1] == b"\n")
            while remove_end < end and data[remove_end : remove_end + 1] in (
                b" ",
                b"\t",
            ):
                next_line = data.find(b"\n", remove_end, end)
                remove_end = end if next_line < 0 else next_line + 1
            return data[:line_start] + data[remove_end:]
        line_start = line_end + 1
    return data


def _old_frontmatter_bounds(data: bytes) -> tuple[int, int]:
    start = 4
    while start <= len(data):
        end = data.find(b"\n", start)
        end = len(data) if end < 0 else end
        if data[start:end] == b"---":
            return 4, start
        if end == len(data):
            break
        start = end + 1
    raise ValueError("missing frontmatter")


def _old_set_task_fields(data: bytes, status: str, status_at: str) -> bytes:
    from varde_core.yamlio import dump_yaml

    start, end = _old_frontmatter_bounds(data)
    fields = {
        "status": dump_yaml(status).splitlines()[1],
        "status_at": dump_yaml(status_at).splitlines()[1],
    }
    lines = data[start:end].splitlines(keepends=True)
    found: set[str] = set()
    output = []
    for line in lines:
        key = (
            line.split(b":", 1)[0].decode("utf-8", errors="ignore")
            if b":" in line
            else ""
        )
        if key in fields:
            output.append(f"{key}: {fields[key]}\n".encode())
            found.add(key)
        else:
            output.append(line)
    insertion = b"".join(
        f"{key}: {fields[key]}\n".encode() for key in fields if key not in found
    )
    return data[:start] + b"".join(output) + insertion + data[end:]


@pytest.mark.parametrize(
    "raw",
    (
        b"---\nid: one\nstatus: todo\nstatus_at: old\n---\nbody\n",
        b"---\nid: one\ncustom: keep\n---\nbody",
        b"---\nstatus: todo\nstatus: blocked\n---\nbody\n",
    ),
)
def test_task_field_patcher_matches_old_line_editor(raw: bytes) -> None:
    expected = _old_set_task_fields(raw, "active", "2026-10-23T10:00:00Z")
    actual = patch_fields(
        raw,
        set_fields={"status": "active", "status_at": "2026-10-23T10:00:00Z"},
    )
    assert actual == expected


def test_memory_plan_writer_updates_record_and_task(tmp_path: Path) -> None:
    memory = MemoryPlans()
    raw = _document(type="plan", id="active", owner="alice", custom="keep")
    task_raw = _document(type="task", id="one", status="todo")
    task = TaskRecord(
        "one",
        {"type": "task", "id": "one", "status": "todo"},
        task_raw,
        0,
        str(tmp_path / "plans/active/tasks/one.md"),
    )
    memory.records.append(
        PlanRecord(
            "active",
            {"type": "plan", "id": "active", "owner": "alice", "custom": "keep"},
            raw,
            0,
            str(tmp_path / "plans/active/plan.md"),
            tasks=(task,),
        )
    )
    updated = memory.set_owner(memory.records[0], "bob")
    assert updated.fields["owner"] == "bob"
    assert updated.extra["custom"] == "keep"
    assert memory.records[0].fields["owner"] == "bob"
    fresh_task = memory.get_by_path(task.path)
    memory.set_task_status(
        TaskRecord(task.id, fresh_task.fields, fresh_task.raw, 0, task.path),
        "active",
        status_at="now",
        transitions={"todo": frozenset({"active"})},
    )
    assert memory.records[0].tasks[0].fields["status"] == "active"


def test_task_status_writer_validates_transition_from_current_record(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "plans" / "active" / "tasks"
    folder.mkdir(parents=True)
    path = folder / "one.md"
    path.write_bytes(_document(type="task", id="one", status="done"))
    repository = FilesPlans(tmp_path)
    task = repository.get_by_path(str(path))
    with pytest.raises(Invalid):
        repository.set_task_status(
            task, "active", status_at="now", transitions={"todo": frozenset({"active"})}
        )


def test_plan_writer_times_out_on_plan_lock(tmp_path: Path) -> None:
    folder = tmp_path / "plans" / "active"
    folder.mkdir(parents=True)
    path = folder / "plan.md"
    path.write_bytes(_document(type="plan", id="active"))
    repository = FilesPlans(tmp_path)
    record = repository.get_by_path(str(path))
    from varde_data.backends.files import plans_write

    previous_timeout = plans_write.LOCK_TIMEOUT
    plans_write.LOCK_TIMEOUT = 0.01
    with file_lock(folder / ".plan.lock", timeout=1):
        try:
            with pytest.raises(Locked):
                repository.set_owner(record, "alice")
        finally:
            plans_write.LOCK_TIMEOUT = previous_timeout


def test_reference_precedence_ambiguity_and_missing(plans, tmp_path: Path) -> None:
    if isinstance(plans, MemoryPlans):
        _seed_memory(plans, tmp_path)
    else:
        first = tmp_path / "plans" / "2026-10-23-alpha"
        second = tmp_path / "plans" / "2026-10-24-alpha"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        (first / "plan.md").write_bytes(_document(id="other", type="plan"))
        (second / "plan.md").write_bytes(_document(id="other-two", type="plan"))
    with pytest.raises(NotFound):
        plans.get("absent")
    if not isinstance(plans, MemoryPlans):
        with pytest.raises(Conflict):
            plans.get("alpha")
        assert plans.get("other").id == "other"


def test_file_reference_resolution_tier_order(tmp_path: Path) -> None:
    root = tmp_path / "plans"
    documents = (
        ("id-target", "tier-ref"),
        ("tier-ref", "other"),
        ("dirname-target", "other"),
        ("2026-10-23-dirname-target", "suffix-other"),
        ("2026-10-23-suffix-only", "suffix-other"),
    )
    for dirname, identifier in documents:
        folder = root / dirname
        folder.mkdir(parents=True)
        (folder / "plan.md").write_bytes(_document(type="plan", id=identifier))

    reader = FilesPlans(tmp_path)
    assert Path(reader.get("tier-ref").path).parent.name == "id-target"
    assert Path(reader.get("dirname-target").path).parent.name == "dirname-target"
    assert Path(reader.get("suffix-only").path).parent.name == "2026-10-23-suffix-only"


@pytest.mark.parametrize("plan_id", ('"quoted-id"', "'odd & id'", '"odd # id"'))
def test_file_reference_resolution_parses_quoted_and_yaml_special_ids(
    tmp_path: Path, plan_id: str
) -> None:
    folder = tmp_path / "plans" / "some-folder"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text(
        f"---\ntype: plan\nid: {plan_id}\n---\n", encoding="utf-8"
    )
    expected = plan_id[1:-1]

    record = FilesPlans(tmp_path).get(expected)

    assert record.fields["id"] == expected


def test_file_reference_ignores_non_plan_kind_at_directory_tier(
    tmp_path: Path,
) -> None:
    named = tmp_path / "plans" / "same"
    suffix = tmp_path / "plans" / "2026-01-01-same"
    named.mkdir(parents=True)
    suffix.mkdir(parents=True)
    (named / "plan.md").write_bytes(_document(type="note", id="other"))
    (suffix / "plan.md").write_bytes(_document(type="plan", id="fallback"))

    record = FilesPlans(tmp_path).get("same")

    assert record.id == "fallback"
    assert Path(record.path).parent.name == "2026-01-01-same"


def test_file_reference_skips_invalid_yaml_in_directory_tier(tmp_path: Path) -> None:
    named = tmp_path / "plans" / "broken"
    suffix = tmp_path / "plans" / "2026-01-01-broken"
    named.mkdir(parents=True)
    suffix.mkdir(parents=True)
    (named / "plan.md").write_bytes(b"---\nid: broken\ninvalid: [\n---\n")
    (suffix / "plan.md").write_bytes(_document(type="plan", id="fallback"))

    record = FilesPlans(tmp_path).get("broken")

    assert record.id == "fallback"


def test_file_get_parses_multiline_and_unicode_whitespace_ids(tmp_path: Path) -> None:
    multiline = tmp_path / "plans" / "multiline" / "plan.md"
    unicode_space = tmp_path / "plans" / "unicode" / "plan.md"
    multiline.parent.mkdir(parents=True)
    unicode_space.parent.mkdir(parents=True)
    multiline.write_bytes(b"---\ntype: plan\nid: foo\n  bar\n---\n")
    unicode_space.write_text("---\ntype: plan\nid: foo\u00a0\n---\n", encoding="utf-8")

    assert FilesPlans(tmp_path).get("foo bar").path == str(multiline)
    assert FilesPlans(tmp_path).get("foo\u00a0").path == str(unicode_space)


def test_file_get_skips_yaml_parse_for_simple_nonmatching_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from varde_data.backends.files import plans as file_plans

    for name, identifier in (("other", "different"), ("target", "wanted")):
        folder = tmp_path / "plans" / name
        folder.mkdir(parents=True)
        (folder / "plan.md").write_bytes(_document(type="plan", id=identifier))
    real_parse = file_plans.parse
    parsed = []

    def track_parse(data):
        parsed.append(data)
        return real_parse(data)

    monkeypatch.setattr(file_plans, "parse", track_parse)

    record = FilesPlans(tmp_path).get("wanted")

    assert record.id == "wanted"
    assert len(parsed) == 2
    assert all(b"id: different" not in source for source in parsed)


@pytest.mark.parametrize(
    ("ref", "documents"),
    [
        ("same-id", (("first", "same-id"), ("second", "same-id"))),
        ("same-dir", (("same-dir", "first"), ("nested/same-dir", "second"))),
        (
            "same-suffix",
            (("2026-10-22-same-suffix", "first"), ("2026-10-23-same-suffix", "second")),
        ),
    ],
)
def test_file_reference_ambiguity_in_each_tier(
    tmp_path: Path, ref: str, documents: tuple[tuple[str, str], ...]
) -> None:
    root = tmp_path / "plans"
    for dirname, identifier in documents:
        folder = root / dirname
        folder.mkdir(parents=True)
        (folder / "plan.md").write_bytes(_document(type="plan", id=identifier))

    with pytest.raises(Conflict, match="ambiguous"):
        FilesPlans(tmp_path).get(ref)


def test_file_get_parses_review_and_tasks_only_for_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from varde_data.backends.files import plans as file_plans

    for name in ("first", "winner", "last"):
        folder = tmp_path / "plans" / name
        (folder / "tasks").mkdir(parents=True)
        (folder / "plan.md").write_bytes(_document(type="plan", id=name))
        (folder / "tasks" / "one.md").write_bytes(_document(type="task"))
    loaded = []
    with_review = file_plans.FilesPlans._with_review
    with_tasks = file_plans.FilesPlans._with_tasks

    def track_review(self, record):
        loaded.append(("review", Path(record.path).parent.name))
        return with_review(self, record)

    def track_tasks(self, record):
        loaded.append(("tasks", Path(record.path).parent.name))
        return with_tasks(self, record)

    monkeypatch.setattr(file_plans.FilesPlans, "_with_review", track_review)
    monkeypatch.setattr(file_plans.FilesPlans, "_with_tasks", track_tasks)

    result = FilesPlans(tmp_path).get("winner")

    assert result.id == "winner"
    assert loaded == [("review", "winner"), ("tasks", "winner")]


def test_get_by_path_parses_only_requested_plan_file(tmp_path: Path) -> None:
    folder = tmp_path / "plans" / "known"
    (folder / "tasks").mkdir(parents=True)
    (folder / "plan.md").write_bytes(_document(type="plan", id="known"))
    (folder / "tasks" / "task.md").write_bytes(_document(type="task", id="task"))
    (folder / "review.md").write_bytes(_document(verdict="approved"))

    record = FilesPlans(tmp_path).get_by_path(str(folder / "plan.md"))

    assert record.id == "known"
    assert record.review_verdict == "approved"
    assert [task.id for task in record.tasks] == ["task"]


@pytest.mark.parametrize("invalid_path", ("missing", "outside", "unparseable"))
def test_get_by_path_raises_not_found_for_invalid_paths(
    tmp_path: Path, invalid_path: str
) -> None:
    plans = FilesPlans(tmp_path)
    missing = tmp_path / "plans" / "missing" / "plan.md"
    outside = tmp_path / "outside.md"
    unparseable = tmp_path / "plans" / "bad" / "plan.md"
    outside.write_bytes(_document(type="plan", id="outside"))
    unparseable.parent.mkdir(parents=True)
    unparseable.write_bytes(b"not frontmatter")

    path = {
        "missing": missing,
        "outside": outside,
        "unparseable": unparseable,
    }[invalid_path]

    with pytest.raises(NotFound):
        plans.get_by_path(str(path))


def test_plan_discovery_keeps_nested_task_under_notes(tmp_path: Path) -> None:
    folder = tmp_path / "plans" / "parent"
    nested_task = folder / "notes" / "builder-fix" / "task.md"
    nested_task.parent.mkdir(parents=True)
    (folder / "plan.md").write_bytes(_document(type="plan", id="parent"))
    nested_task.write_bytes(_document(type="task", id="builder-fix"))

    reader = FilesPlans(tmp_path)

    assert [record.id for record in reader.list().records] == [
        "builder-fix",
        "parent",
    ]
    assert reader.get("builder-fix").id == "builder-fix"


def test_owner_lookup(plans, tmp_path: Path) -> None:
    if isinstance(plans, MemoryPlans):
        _seed_memory(plans, tmp_path)
        plans.records.append(
            PlanRecord(
                "alice-task",
                {"type": "task", "owner": "alice"},
                _document(type="task", owner="alice"),
                10.0,
                str(tmp_path / "plans/alice-task/task.md"),
                artifact_type="task",
            )
        )
        assert [record.id for record in plans.owner_lookup("alice")] == [
            "2026-10-23-alpha"
        ]
        return
    folder = tmp_path / "plans" / "owned"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_bytes(_document(type="plan", owner="alice"))
    standalone = tmp_path / "plans" / "standalone-task"
    standalone.mkdir()
    (standalone / "task.md").write_bytes(_document(type="task", owner="alice"))
    assert len(plans.owner_lookup("alice")) == 1


def test_owner_lookup_reads_only_plan_documents(tmp_path: Path, monkeypatch) -> None:
    plan_count = 4
    plan_paths = []
    for index in range(plan_count):
        folder = tmp_path / "plans" / f"plan-{index}"
        tasks = folder / "tasks"
        tasks.mkdir(parents=True)
        plan = folder / "plan.md"
        plan.write_bytes(
            _document(
                id=f"plan-{index}",
                type="plan",
                owner="alice" if index == 2 else "bob",
            )
        )
        plan_paths.append(plan)
        (folder / "review.md").write_bytes(_document(verdict="approved"))
        (tasks / "01-work.md").write_bytes(_document(type="task", owner="alice"))

    read_bytes = Path.read_bytes
    reads = []

    def counted_read_bytes(path: Path) -> bytes:
        reads.append(path)
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)

    records = FilesPlans(tmp_path).owner_lookup("alice")

    assert [record.id for record in records] == ["plan-2"]
    assert reads == plan_paths


def test_owner_lookup_prefers_active_plan_over_same_owner_archive(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "plans"
    active = folder / "active" / "plan.md"
    archived = folder / "archive" / "old" / "plan.md"
    active.parent.mkdir(parents=True)
    archived.parent.mkdir(parents=True)
    active.write_bytes(_document(id="active", type="plan", owner="alice"))
    archived.write_bytes(_document(id="old", type="plan", owner="alice"))

    assert [record.id for record in FilesPlans(tmp_path).owner_lookup("alice")] == [
        "active"
    ]


def test_nested_archive_matches_status_discovery(tmp_path: Path) -> None:
    active = tmp_path / "plans" / "group" / "active" / "plan.md"
    archived = tmp_path / "plans" / "group" / "archive" / "nested" / "plan.md"
    active.parent.mkdir(parents=True)
    archived.parent.mkdir(parents=True)
    active.write_bytes(_document(type="plan", id="active"))
    archived.write_bytes(_document(type="plan", id="nested-archive"))
    plans = FilesPlans(tmp_path)

    assert [record.id for record in plans.list().records] == ["active"]
    archived_record = next(
        record
        for record in plans.list(include_archived=True).records
        if record.id == "nested-archive"
    )
    assert archived_record.archived


def test_plan_discovery_finds_nested_plan_documents(tmp_path: Path) -> None:
    folder = tmp_path / "plans" / "parent"
    nested = folder / "notes" / "nested"
    nested.mkdir(parents=True)
    (folder / "plan.md").write_bytes(_document(type="plan", id="parent"))
    (nested / "plan.md").write_bytes(_document(type="plan", id="nested"))

    reader = FilesPlans(tmp_path)

    assert [record.id for record in reader.list().records] == ["nested", "parent"]
    assert reader.get("nested").id == "nested"


def test_unreadable_plan_directory_increments_skipped(
    tmp_path: Path, monkeypatch
) -> None:
    from varde_data.backends.files import plans as file_plans

    root = tmp_path / "plans"
    blocked = root / "blocked"
    blocked.mkdir(parents=True)
    real_scandir = file_plans.os.scandir

    def unreadable(path):
        if Path(path) == blocked:
            raise OSError("unreadable directory")
        return real_scandir(path)

    monkeypatch.setattr(file_plans.os, "scandir", unreadable)

    result = FilesPlans(tmp_path).list()

    assert result.skipped == 1
    assert result.records == ()


def test_nonempty_string_coercion_for_plan_and_task_fields(tmp_path: Path) -> None:
    root = tmp_path / "plans"
    plan_folder = root / "plan-folder"
    tasks = plan_folder / "tasks"
    tasks.mkdir(parents=True)
    (plan_folder / "plan.md").write_text(
        "---\nartifact_type: ''\ntype: plan\nid: ''\n---\n", encoding="utf-8"
    )
    (tasks / "task-stem.md").write_text(
        "---\nartifact_type: []\ntype: task\nid: ''\n---\n", encoding="utf-8"
    )
    (root / "fallback-kind").mkdir(parents=True)
    (root / "fallback-kind" / "plan.md").write_text(
        "---\nartifact_type: 12\ntype: plan\n---\n", encoding="utf-8"
    )
    (root / "nonstring-kind").mkdir(parents=True)
    (root / "nonstring-kind" / "plan.md").write_text(
        "---\nartifact_type: []\ntype: 12\nid: []\n---\n", encoding="utf-8"
    )
    (tasks / "task-nonstring-id.md").write_text(
        "---\ntype: task\nid: []\n---\n", encoding="utf-8"
    )

    records = FilesPlans(tmp_path).list().records
    plan = next(record for record in records if record.id == "plan-folder")
    assert plan.artifact_type == "plan"
    assert {task.id for task in plan.tasks} == {"task-stem", "task-nonstring-id"}
    assert next(record for record in records if record.id == "fallback-kind")
    nonstring = next(record for record in records if record.id == "nonstring-kind")
    assert nonstring.artifact_type == "plan"


def test_stale_temp_cleanup_visits_plan_directory_once(
    tmp_path: Path, monkeypatch
) -> None:
    from varde_data.backends.files import plans as file_plans

    folder = tmp_path / "plans" / "nested"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_bytes(_document(type="plan"))
    stale = folder / ".write.123.tmp"
    stale.write_bytes(b"stale")
    os.utime(stale, (0, 0))
    calls = []
    cleanup = file_plans.remove_stale_temps

    def counted(directory: Path, older_than: float) -> int:
        calls.append(directory)
        return cleanup(directory, older_than)

    monkeypatch.setattr(file_plans, "remove_stale_temps", counted)
    reader = FilesPlans(tmp_path)
    reader.list()
    reader.list()
    assert calls == [folder]
    assert not stale.exists()


def test_version_tracks_changes_and_measures_300_plan_walk(tmp_path: Path) -> None:
    """Filesystem version and traversal contracts are files-backend-only."""
    root = tmp_path / "plans"
    for index in range(300):
        folder = root / f"plan-{index:03d}"
        (folder / "tasks").mkdir(parents=True)
        (folder / "plan.md").write_bytes(_document(id=f"plan-{index:03d}", type="plan"))
        (folder / "tasks" / "one.md").write_bytes(_document(type="task", title="one"))
    reader = FilesPlans(tmp_path)
    started = time.perf_counter()
    before = reader.version()
    elapsed_ms = (time.perf_counter() - started) * 1000
    file_count = sum(1 for path in root.rglob("*") if path.is_file())
    assert file_count == 600
    measured_baseline_ms = 982.009
    assert elapsed_ms < measured_baseline_ms * 10
    task = root / "plan-000" / "tasks" / "one.md"
    old = reader.version()
    task.write_bytes(_document(type="task", title="edit"))
    assert reader.version() != old
    same_size = task.stat().st_size
    same_size_before = reader.version()
    task.write_bytes(b"x" * same_size)
    assert reader.version() != same_size_before
    raced = reader.version()
    assert raced.is_racy_at(task.stat().st_mtime_ns)
    task.unlink()
    assert reader.version() != before
    (root / "new").mkdir()
    (root / "new" / "plan.md").write_bytes(_document(type="plan"))
    assert reader.version() != before
    print(f"300-plan version token: files={file_count}, duration_ms={elapsed_ms:.3f}")


def test_indexed_reads_refresh_after_membership_and_content_changes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plans"
    plan_dir = root / "2026-01-01-indexed"
    tasks_dir = plan_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    plan = plan_dir / "plan.md"
    task = tasks_dir / "one.md"
    plan.write_bytes(_document(id="indexed", type="plan", owner="alice"))
    task.write_bytes(_document(id="one", type="task", title="old"))
    reader = FilesPlans(tmp_path)

    assert reader.get("indexed").tasks[0].fields["title"] == "old"
    assert [record.id for record in reader.owner_lookup("alice")] == ["indexed"]
    task.write_bytes(_document(id="one", type="task", title="new"))
    assert reader.get("indexed").tasks[0].fields["title"] == "new"

    added = tasks_dir / "two.md"
    added.write_bytes(_document(id="two", type="task", title="added"))
    assert [record.id for record in reader.get("indexed").tasks] == ["one", "two"]
    added.rename(tasks_dir / "renamed.md")
    assert [record.id for record in reader.get("indexed").tasks] == ["one", "two"]
    (tasks_dir / "renamed.md").unlink()
    assert [record.id for record in reader.get("indexed").tasks] == ["one"]


def _version_fixture(tmp_path: Path) -> tuple[FilesPlans, Path, Path, Path]:
    folder = tmp_path / "plans" / "2026-01-01-versioned"
    tasks = folder / "tasks"
    notes = folder / "notes"
    tasks.mkdir(parents=True)
    notes.mkdir()
    plan = folder / "plan.md"
    review = folder / "review.md"
    task = tasks / "one.md"
    note = notes / "context.md"
    plan.write_bytes(_document(id="versioned", type="plan"))
    review.write_text("---\nverdict: approved\n---\n")
    task.write_bytes(_document(id="one", type="task", title="same"))
    note.write_text("before\n")
    return FilesPlans(tmp_path), folder, tasks, note


def test_version_ignores_notes_file_edits(tmp_path: Path) -> None:
    reader, _, _, note = _version_fixture(tmp_path)
    baseline = reader.version()
    note.write_text("after!\n")
    assert reader.version() == baseline


def test_plan_index_and_discovery_terminate_on_directory_symlink_loops(
    tmp_path: Path,
) -> None:
    plan_dir = tmp_path / "plans" / "looped"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_bytes(_document(id="looped", type="plan"))
    for name in ("up-one", "up-two"):
        try:
            (plan_dir / name).symlink_to("..", target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlinks unavailable: {exc}")
    reader = FilesPlans(tmp_path)

    version = reader.version()
    listed = reader.list()

    assert version.value
    assert [record.id for record in listed.records] == ["looped"]
    assert reader.get("looped").id == "looped"


def test_version_tracks_reader_artifact_add_remove_rename_and_rewrite(
    tmp_path: Path,
) -> None:
    reader, folder, tasks, _ = _version_fixture(tmp_path)
    task = tasks / "one.md"
    review = folder / "review.md"
    baseline = reader.version()

    added_plan_dir = tmp_path / "plans" / "2026-01-02-added"
    added_plan_dir.mkdir()
    added_plan = added_plan_dir / "plan.md"
    added_plan.write_bytes(_document(id="added", type="plan"))
    after_plan_add = reader.version()
    assert after_plan_add != baseline
    renamed_plan = added_plan_dir / "task.md"
    added_plan.rename(renamed_plan)
    after_plan_rename = reader.version()
    assert after_plan_rename != after_plan_add
    renamed_plan.unlink()
    after_plan_remove = reader.version()
    assert after_plan_remove != after_plan_rename

    added = tasks / "two.md"
    added.write_bytes(_document(id="two", type="task", title="added"))
    after_add = reader.version()
    assert after_add != baseline
    added.unlink()
    after_remove = reader.version()
    assert after_remove != after_add

    renamed = tasks / "renamed.md"
    task.rename(renamed)
    after_rename = reader.version()
    assert after_rename != after_remove
    renamed.rename(task)
    after_restore = reader.version()
    assert after_restore != after_rename

    review.write_text("---\nverdict: rejected\n---\n")
    after_review_edit = reader.version()
    assert after_review_edit != after_restore
    review.rename(folder / "review.old")
    after_review_remove = reader.version()
    assert after_review_remove != after_review_edit
    (folder / "review.old").rename(review)
    assert reader.version() != after_review_remove

    same_size = task.stat().st_size
    previous = reader.version()
    task.write_bytes(b"x" * same_size)
    raced = reader.version()
    assert raced != previous or raced.is_racy_at(task.stat().st_mtime_ns)


def _reference_plan_paths(root: Path, include_archived: bool) -> tuple[list[Path], int]:
    if not root.exists():
        return [], 0
    try:
        with os.scandir(root) as scanner:
            entries = sorted(scanner, key=lambda entry: entry.name)
    except OSError:
        return [], 1
    has_plan = any(
        entry.name == "plan.md" and (entry.is_file() or entry.is_dir())
        for entry in entries
    )
    paths: list[Path] = []
    skipped = 0
    for entry in entries:
        path = root / entry.name
        try:
            if entry.is_dir():
                if not include_archived and path.name == "archive":
                    continue
                if path.name == "tasks" and has_plan:
                    continue
                nested, nested_skipped = _reference_plan_paths(path, include_archived)
                paths.extend(nested)
                skipped += nested_skipped
            elif (
                path.name in {"plan.md", "task.md"}
                and (entry.is_file() or entry.is_symlink())
                and (path.name == "plan.md" or not (path.parent / "plan.md").exists())
            ):
                paths.append(path)
        except OSError:
            skipped += 1
    return paths, skipped


class FullScanPlans(FilesPlans):
    """Test reference using the original uncached recursive directory scan."""

    def _plan_paths(self, include_archived: bool) -> tuple[list[Path], int]:
        return _reference_plan_paths(self.root, include_archived)


def _assert_plan_readers_match(indexed: FilesPlans, reference: FilesPlans) -> None:
    for archived in (False, True):
        for tasks in (False, True):
            assert indexed.list(
                include_archived=archived, include_tasks=tasks
            ) == reference.list(include_archived=archived, include_tasks=tasks)
    records = reference.list(include_archived=True).records
    for record in records:
        assert indexed.get(record.id, include_archived=True) == reference.get(
            record.id, include_archived=True
        )
        assert indexed.get_by_path(record.path) == reference.get_by_path(record.path)
    for owner in ("alice", "bob", "nobody"):
        assert indexed.owner_lookup(
            owner, include_archived=True
        ) == reference.owner_lookup(owner, include_archived=True)


def test_index_matches_plain_full_scan_reference_after_mutations(
    tmp_path: Path,
) -> None:
    plans_root = tmp_path / "plans"
    plan_dir = plans_root / "2026-01-01-parent"
    (plan_dir / "tasks").mkdir(parents=True)
    (plan_dir / "notes" / "nested").mkdir(parents=True)
    archived_dir = plans_root / "archive" / "old"
    archived_dir.mkdir(parents=True)
    plan = plan_dir / "plan.md"
    task = plan_dir / "tasks" / "one.md"
    nested_task = plan_dir / "notes" / "nested" / "task.md"
    archived_plan = archived_dir / "plan.md"
    plan.write_bytes(_document(id="parent", type="plan", owner="alice"))
    (plan_dir / "review.md").write_bytes(_document(verdict="approved"))
    task.write_bytes(_document(id="one", type="task", title="same"))
    nested_task.write_bytes(_document(id="nested", type="task", owner="bob"))
    archived_plan.write_bytes(_document(id="old", type="plan", owner="alice"))
    indexed, reference = FilesPlans(tmp_path), FullScanPlans(tmp_path)

    _assert_plan_readers_match(indexed, reference)
    task.write_bytes(_document(id="one", type="task", title="edit"))
    _assert_plan_readers_match(indexed, reference)
    task.rename(task.with_name("renamed.md"))
    _assert_plan_readers_match(indexed, reference)
    (task.parent / "renamed.md").unlink()
    _assert_plan_readers_match(indexed, reference)
    nested_task.write_bytes(_document(id="nested", type="task", owner="alice"))
    _assert_plan_readers_match(indexed, reference)
    plan_dir.rename(plan_dir.with_name("2026-01-01-renamed"))
    _assert_plan_readers_match(indexed, reference)


@pytest.mark.parametrize("artifact", ("plan", "task", "review"))
def test_same_size_rewrite_with_restored_mtime_changes_read(
    tmp_path: Path, artifact: str
) -> None:
    folder = tmp_path / "plans" / "2026-01-01-restored"
    tasks = folder / "tasks"
    tasks.mkdir(parents=True)
    plan = folder / "plan.md"
    task = tasks / "one.md"
    review = folder / "review.md"
    plan.write_bytes(_document(id="restored", type="plan", status="todo"))
    task.write_bytes(_document(id="one", type="task", status="todo"))
    review.write_bytes(_document(verdict="approved"))
    reader = FilesPlans(tmp_path)
    before = reader.version()
    reader.get("restored")
    path = {"plan": plan, "task": task, "review": review}[artifact]
    original_stat = path.stat()
    if artifact == "plan":
        replacement = _document(id="restored", type="plan", status="done")
    elif artifact == "task":
        replacement = _document(id="one", type="task", status="done")
    else:
        replacement = _document(verdict="rejected")
    assert len(replacement) == original_stat.st_size
    path.write_bytes(replacement)
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    record = reader.get("restored")
    assert reader.version() != before
    if artifact == "plan":
        assert record.status == "done"
    elif artifact == "task":
        assert record.tasks[0].fields["status"] == "done"
    else:
        assert record.review_verdict == "rejected"


def test_coarse_mtime_cache_rechecks_files_and_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_key = plans_index_module._key

    def coarse_key(info: os.stat_result) -> tuple[int, int, int, int]:
        key = original_key(info)
        return (
            key[0] // 1_000_000_000 * 1_000_000_000,
            key[1] // 1_000_000_000 * 1_000_000_000,
            key[2],
            key[3],
        )

    monkeypatch.setattr(plans_index_module, "_key", coarse_key)
    plans_root = tmp_path / "plans"
    plan_dir = plans_root / "coarse"
    plan_dir.mkdir(parents=True)
    plan = plan_dir / "plan.md"
    plan.write_bytes(_document(id="coarse", type="plan", status="todo"))
    quantized = (time.time_ns() // 1_000_000_000) * 1_000_000_000
    os.utime(plan, ns=(quantized, quantized))
    os.utime(plan_dir, ns=(quantized, quantized))
    os.utime(plans_root, ns=(quantized, quantized))
    reader = FilesPlans(tmp_path)
    assert reader.get("coarse").status == "todo"

    plan.write_bytes(_document(id="coarse", type="plan", status="done"))
    os.utime(plan, ns=(quantized, quantized))
    before_rewrite_version = reader.version()
    plan.write_bytes(_document(id="coarse", type="plan", status="todo"))
    os.utime(plan, ns=(quantized, quantized))
    racy_version = reader.version()
    assert racy_version != before_rewrite_version or racy_version.is_racy_at(
        plan.stat().st_mtime_ns
    )
    plan.write_bytes(_document(id="coarse", type="plan", status="done"))
    os.utime(plan, ns=(quantized, quantized))
    assert reader.get("coarse").status == "done"

    added = plans_root / "added"
    added.mkdir()
    (added / "plan.md").write_bytes(_document(id="added", type="plan"))
    os.utime(plans_root, ns=(quantized, quantized))
    assert {record.id for record in reader.list().records} == {"coarse", "added"}


def test_touch_only_changes_artifact_version(tmp_path: Path) -> None:
    folder = tmp_path / "plans" / "touch"
    folder.mkdir(parents=True)
    plan = folder / "plan.md"
    plan.write_bytes(_document(id="touch", type="plan"))
    reader = FilesPlans(tmp_path)
    before = reader.version()
    previous = plan.stat()
    os.utime(plan, ns=(previous.st_atime_ns, previous.st_mtime_ns + 5_000_000_000))
    assert reader.version() != before


def test_fields_cache_does_not_store_across_read_parse_race(tmp_path: Path) -> None:
    path = tmp_path / "source.md"
    path.write_bytes(_document(status="todo"))
    index = FilesPlans(tmp_path)._index

    def rewrite_while_parsing(raw: bytes) -> tuple[dict[str, object], object]:
        parsed, remainder = parse(raw)
        path.write_bytes(_document(status="done"))
        return parsed, remainder

    _, parsed = index.fields(path, rewrite_while_parsing)
    assert parsed["status"] == "todo"
    assert str(path) not in index._fields
    _, current = index.fields(path, parse)
    assert current["status"] == "done"


def test_fields_cache_isolated_from_callers_and_parser_modes(tmp_path: Path) -> None:
    path = tmp_path / "source.md"
    path.write_bytes(_document(depends_on="[first]\r\n"))
    old_ns = time.time_ns() - 10_000_000_000
    os.utime(path, ns=(old_ns, old_ns))
    index = FilesPlans(tmp_path)._index

    def raw_parser(raw: bytes) -> tuple[dict[str, object], object]:
        return {"raw": raw.decode()}, None

    def other_parser(raw: bytes) -> tuple[dict[str, object], object]:
        return {"raw": "other parser"}, None

    _, crlf = index.fields(path, raw_parser)
    _, normalized = index.fields(path, raw_parser, normalize_newlines=True)
    assert crlf["raw"] != normalized["raw"]
    changed = dict(crlf)
    changed["raw"] = "caller mutation"
    _, reread = index.fields(path, raw_parser)
    assert reread == crlf
    _, parsed_by_other = index.fields(path, other_parser)
    assert parsed_by_other == {"raw": "other parser"}

    plan_dir = tmp_path / "plans" / "mutable"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_bytes(
        _document(id="mutable", type="plan", depends_on="[first]")
    )
    old_ns = time.time_ns() - 10_000_000_000
    os.utime(plan_dir / "plan.md", ns=(old_ns, old_ns))
    reader = FilesPlans(tmp_path)
    first = reader.get("mutable")
    first.fields["depends_on"].append("mutated")  # type: ignore[union-attr]
    assert reader.get("mutable").fields["depends_on"] == ["first"]


def test_deleting_plan_directories_releases_index_entries(tmp_path: Path) -> None:
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    reader = FilesPlans(tmp_path)
    index = reader._index
    for cycle in range(8):
        folder = plans_root / f"plan-{cycle}"
        tasks = folder / "tasks"
        tasks.mkdir(parents=True)
        (folder / "plan.md").write_bytes(_document(id=f"plan-{cycle}", type="plan"))
        (tasks / "task.md").write_bytes(_document(id=f"task-{cycle}", type="task"))
        old_ns = time.time_ns() - 10_000_000_000
        os.utime(folder / "plan.md", ns=(old_ns, old_ns))
        os.utime(tasks / "task.md", ns=(old_ns, old_ns))
        reader.list()
        assert index._bytes and index._fields and index._artifacts
        shutil.rmtree(folder)
        reader.list()
        reader.version()
        assert index._directories == {
            os.fspath(plans_root): index._directories[os.fspath(plans_root)]
        }
        assert index._children.keys() == {os.fspath(plans_root)}
        assert not index._artifacts
        assert not index._bytes
        assert not index._fields
