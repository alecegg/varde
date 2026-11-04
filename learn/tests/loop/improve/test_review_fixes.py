"""Guards added after the plan review: approval, paths, ids, shim, EOLs, bypass."""

from __future__ import annotations

import io
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from varde_learn.docs.pages.blocks.statement import quote
from varde_learn.docs.pages.lines import parse_lines
from varde_learn.loop import cli_skills_accept, cli_skills_extract, cli_skills_report
from varde_learn.loop.improve import (
    apply,
    approval,
    filediff,
    shim,
    tool_bypass,
    tool_entry,
)
from varde_learn.loop.improve import record as rec
from varde_learn.memory import store

TOPIC = (
    "---\ntopic: varde-x/do\nversion: 1\nsummary: S\n---\n\n"
    "Step one is to read the input files and list what changed in each.\n"
    "Step two covers every changed file in turn with a short summary.\n"
)


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


@pytest.fixture
def world(tmp_path, monkeypatch):
    pkg = tmp_path / "pkg"
    topic = pkg / "how" / "varde-x" / "do.md"
    topic.parent.mkdir(parents=True)
    topic.write_text(TOPIC)
    memory = tmp_path / "memory"
    monkeypatch.setattr(store, "memory_root", lambda _cwd: memory)
    assert cli_skills_extract.run(["varde-x", "do"], Io(), roots=[pkg]) == 0
    [record] = rec.list_records(memory)
    return pkg, memory, record


def accept(pkg: Path, record_id: str, out: Io | None = None) -> int:
    return cli_skills_accept.run([record_id], out or Io(), roots=[pkg])


# SECURITY-001: approval


def test_accept_without_approval_names_the_report_page(world, approve) -> None:
    pkg, memory, record = world
    page = approval.report_dir(memory) / "2026-11-01.md"
    page.parent.mkdir(parents=True)
    page.write_text(f"## {record.id}\n\n```ui id={record.id}\n```\n")
    out = Io()
    assert accept(pkg, record.id, out) == 2
    assert str(page) in out.stderr.getvalue()
    assert rec.read_record(memory, record.id).state == "proposed"
    assert "step-tool" not in (pkg / "how/varde-x/do.md").read_text()


def test_accept_needs_the_latest_decision_to_approve(world, approve) -> None:
    pkg, memory, record = world
    approve(memory, record.id, "approved")
    approve(memory, record.id, "denied")
    out = Io()
    assert accept(pkg, record.id, out) == 2
    assert "'denied'" in out.stderr.getvalue()
    approve(memory, "other-id", "approved")
    assert accept(pkg, record.id) == 2
    approve(memory, record.id, "approved")
    assert accept(pkg, record.id) == 0


# SECURITY-001: paths


def test_paths_must_be_source_files_inside_roots(tmp_path) -> None:
    root = tmp_path / "pkg"
    (root / "skills").mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (root / "how").symlink_to(outside)
    paths = [
        str(root / "skills/a/SKILL.md"),  # allowed
        str(root / "step_tools/registry.toml"),  # allowed
        str(root / "README.md"),  # not a source dir
        str(root / "skills/../../escape.md"),  # dot-dot
        "relative/skills/a.md",  # not absolute
        str(outside / "x.md"),  # outside
        str(root / "how/x.md"),  # symlink escape
    ]
    assert approval.outside_roots(paths, [root]) == sorted(paths[2:])


def test_accept_refuses_a_forged_record_outside_the_roots(
    world, approve, tmp_path
) -> None:
    pkg, memory, record = world
    approve(memory, record.id)
    other = tmp_path / "other-root"
    other.mkdir()
    out = Io()
    assert cli_skills_accept.run([record.id], out, roots=[other]) == 2
    assert "outside skill or agent source" in out.stderr.getvalue()
    assert "step-tool" not in (pkg / "how/varde-x/do.md").read_text()


# SECURITY-002


def test_record_ids_are_validated_before_any_path_use(world) -> None:
    pkg, memory, _ = world
    (memory.parent / "evil.json").write_text("{}")
    out = Io()
    assert accept(pkg, "../../evil", out) == 2
    assert "invalid id" in out.stderr.getvalue()
    with pytest.raises(rec.RecordError, match="invalid id"):
        rec.read_record(memory, "../evil")


# CORRECTNESS-001: shim


def fake_install(tmp_path: Path, shebang: str) -> Path:
    bin_dir = tmp_path / "release-1" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    varde = bin_dir / "varde"
    varde.write_text(f"#!{shebang}\nprint('unused')\n")
    varde.chmod(0o755)
    return bin_dir


def run_shim(tmp_path: Path, path_dirs: list[Path], *args: str):
    launcher = shim.install_shim()
    env = {"PATH": os.pathsep.join([*map(str, path_dirs), "/usr/bin", "/bin"])}
    return subprocess.run(  # noqa: S603
        ["/bin/sh", str(launcher), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def fake_python(tmp_path: Path) -> Path:
    python = tmp_path / "release-1" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text('#!/bin/sh\necho "py $@"\n')
    python.chmod(0o755)
    return python


def test_shim_runs_the_wrapper_with_the_interpreter_of_the_installed_varde(
    tmp_path,
) -> None:
    python = fake_python(tmp_path)
    bin_dir = fake_install(tmp_path, str(python))
    done = run_shim(tmp_path, [bin_dir], "varde-x/do", "--flag")
    assert done.returncode == 0
    assert done.stdout.strip() == f"py -m {shim.ENTRY_MODULE} varde-x/do --flag"


def test_shim_follows_a_release_swap_without_being_rewritten(tmp_path) -> None:
    first = fake_python(tmp_path)
    bin_dir = fake_install(tmp_path, str(first))
    assert run_shim(tmp_path, [bin_dir], "a/b").returncode == 0
    moved = tmp_path / "release-2"
    (tmp_path / "release-1").rename(moved)
    new_python = moved / "bin" / "python"
    (moved / "bin" / "varde").write_text(f"#!{new_python}\n")
    assert run_shim(tmp_path, [moved / "bin"], "a/b").returncode == 0


def test_shim_fails_clearly_when_varde_or_interpreter_is_missing(tmp_path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    done = run_shim(tmp_path, [empty], "a/b")
    assert done.returncode != 0
    assert "varde is not on PATH" in done.stderr
    bin_dir = fake_install(tmp_path, str(tmp_path / "gone" / "python"))
    done = run_shim(tmp_path, [bin_dir], "a/b")
    assert done.returncode != 0
    assert "cannot resolve the varde interpreter" in done.stderr


def test_shim_runs_the_real_wrapper_through_a_real_interpreter(tmp_path) -> None:
    bin_dir = fake_install(tmp_path, sys.executable)
    done = run_shim(tmp_path, [bin_dir], "no-such/step")
    assert done.returncode == 2
    assert "no step tool no-such/step" in done.stderr


def test_accepting_an_extraction_installs_an_executable_shim(
    world, approve, private_data_home
) -> None:
    pkg, memory, record = world
    approve(memory, record.id)
    assert accept(pkg, record.id) == 0
    launcher = private_data_home / "varde" / shim.SHIM_NAME
    assert launcher.read_text() == shim.SHIM_TEXT
    assert launcher.stat().st_mode & stat.S_IXUSR
    assert shim.POINTER_PATH in (pkg / "how/varde-x/do.md").read_text()


# CORRECTNESS-002


def test_bypass_registry_failure_gives_a_notice_not_an_exception(monkeypatch) -> None:
    def boom():
        raise tool_entry.ToolError("invalid registry: bad")

    monkeypatch.setattr(tool_bypass, "module_roots", boom)
    rows, notice = tool_bypass.load_rows()
    assert rows == [] and "skipped" in notice and "bad" in notice
    assert tool_bypass.bypass_metric([{"tool_name": "Bash"}], "s", rows) == []


# CORRECTNESS-003


def test_one_bad_record_is_skipped_by_list_and_reported_by_report(world) -> None:
    _, memory, record = world
    (rec.loop_dir(memory) / "broken.json").write_text("{not json")
    (rec.loop_dir(memory) / "Bad Name.json").write_text("{}")
    assert [r.id for r in rec.list_records(memory)] == [record.id]
    records, skipped = rec.scan_records(memory)
    assert len(records) == 1 and len(skipped) == 2
    out = Io()
    assert cli_skills_report.run([], out) == 0
    assert record.id in out.stdout.getvalue()
    assert "skipped broken.json" in out.stderr.getvalue()


# CORRECTNESS-004

CRLF = "---\r\ntopic: varde-x/do\r\n---\r\n\r\nline one\r\nline two\r\nline three\r\n"


def test_diff_round_trips_crlf_form_feed_and_unicode_separators() -> None:
    old = "a\r\nb\x0cc\r\nd e\u0085f\r\nlast"
    new = "a\r\nB\x0cc\r\nd e\u0085f\r\nlast\r\nmore\r\n"
    diff = filediff.make_file_diff("/p", old, new)
    [file_diff] = filediff.parse_diff(diff)
    assert filediff.apply_file_diff(old, file_diff) == new
    created = filediff.make_file_diff("/q", None, CRLF)
    [made] = filediff.parse_diff(created)
    assert filediff.apply_file_diff("", made) == CRLF


def test_apply_reads_and_writes_without_newline_translation(tmp_path) -> None:
    target = tmp_path / "f.md"
    target.write_bytes(CRLF.encode())
    assert apply._read(str(target)) == CRLF
    diff = filediff.make_file_diff(str(target), CRLF, CRLF.replace("two", "2"))
    images = apply.post_images(diff, {str(target): CRLF})
    apply._write_all(images)
    assert target.read_bytes() == CRLF.replace("two", "2").encode()


def test_crlf_topic_fails_closed_without_writing(tmp_path, monkeypatch) -> None:
    pkg = tmp_path / "pkg"
    topic = pkg / "how" / "varde-x" / "do.md"
    topic.parent.mkdir(parents=True)
    topic.write_bytes(TOPIC.replace("\n", "\r\n").encode())
    memory = tmp_path / "memory"
    monkeypatch.setattr(store, "memory_root", lambda _cwd: memory)
    out = Io()
    assert cli_skills_extract.run(["varde-x", "do"], out, roots=[pkg]) == 2
    assert not memory.exists()


def test_statement_string_escapes_every_line_boundary() -> None:
    text = "a\x7f\x85\u2028\u2029 ```b"
    encoded = quote(text)
    assert all(ch not in encoded for ch in "\x7f\x85\u2028\u2029")
    result = parse_lines(f"x = decision(question: {encoded})")
    assert result.errors == []
    assert result.statements[0].props["question"] == text
