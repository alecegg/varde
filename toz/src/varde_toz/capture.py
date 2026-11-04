"""Capture, redact, section, store, and render already-produced text."""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from . import metadata
from .chunk import (
    Chunk,
    chunk_default,
    classify,
    looks_binary,
    strip_ansi,
    truncate,
    truncate_middle,
)
from .config import config_dir, config_int, load_config
from .metadata import identity_at
from .profile import Profile, find_match, load_profiles
from .project import project_root, store_db_path
from .redact_toz import configured_redactor, never_capture, redact_configured
from .store import NewCapture, Store
from .strategies import chunk_with_profile, preview_toc
from .streaming import line_blocks, normalize_and_redact
from .terms import distinctive

STATS_LOG_INSERT = (
    "INSERT INTO stats_log(ts,kind,bytes_in,bytes_out,session) "
    "VALUES(strftime('%s','now'),?,?,?,?)"
)


def _phase_span(name: str):
    import os

    if os.environ.get("VARDE_TOZ_PHASE_TRACE"):
        from varde_toz.phase_trace import span

        return span(name)
    return nullcontext()


MAX_PROFILED_CAPTURE_BYTES = 8 * 1024 * 1024
PREVIEW_LINE_MAX = 240
PREVIEW_DIAGNOSTICS = 6


@dataclass
class CaptureInput:
    stdout: bytes
    stderr: bytes = b""
    label: str | None = None
    source: str = ""
    kind: str = "capture"
    exit_code: int | None = None
    session: str | None = None
    force: bool = False
    defer_index: bool = False
    threshold: int | None = None
    quiet: bool = False
    file_mtime: int | None = None
    file_hash: bytes | None = None
    content_redacted: bool = False


@dataclass(frozen=True)
class CaptureResult:
    status: int
    output: str
    skip_reason: str | None = None

    def __iter__(self):
        # Preserve the existing tuple interface for capture callers.
        yield self.status
        yield self.output


def source_key(source: str) -> str:
    value = source.strip()
    for suffix in (" 2>&1", " 2>/dev/null", " 2> /dev/null"):
        value = value.removesuffix(suffix)
    return " ".join(value.split())


def _command_capture(kind: str) -> bool:
    return kind in ("run", "exec", "script") or kind.startswith("hook:")


def _preview_line(line: str) -> str:
    return truncate(line, PREVIEW_LINE_MAX)


def _diagnostic_level(line: str) -> str | None:
    value = line.lstrip()[:512].lower()
    if (
        value.startswith(("error:", "error[", "fatal:", "test result: failed"))
        or ": error:" in value
        or "panicked at " in value
        or value.endswith(" ... failed")
    ):
        return "error"
    if value.startswith(("warning:", "warning[")) or ": warning:" in value:
        return "warning"
    return None


def _diagnostics(
    stdout: list[str], stderr: list[str]
) -> list[tuple[str, int, str, str]]:
    found = []
    for stream, lines in (("stdout", stdout), ("stderr", stderr)):
        for index, line in enumerate(lines, 1):
            level = _diagnostic_level(line)
            if not level:
                continue
            item = (stream, index, level, _preview_line(line))
            if len(found) < PREVIEW_DIAGNOSTICS:
                found.append(item)
            elif level == "error":
                warning = next(
                    (i for i, old in enumerate(found) if old[2] == "warning"), None
                )
                if warning is not None:
                    found.pop(warning)
                    found.append(item)
    return found


def _collapse(lines: list[str], limit: int) -> list[str]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)
    output: list[str] = []
    index = 0
    while index < len(blocks) and len(output) < limit:
        end = index + 1
        while end < len(blocks) and blocks[end] == blocks[index]:
            end += 1
        collapsed: list[str] = []
        cursor = 0
        while cursor < len(blocks[index]):
            last = cursor + 1
            while (
                last < len(blocks[index])
                and blocks[index][last] == blocks[index][cursor]
            ):
                last += 1
            count = last - cursor
            suffix = f" ×{count}" if count > 1 else ""
            collapsed.append(
                truncate(blocks[index][cursor], PREVIEW_LINE_MAX - len(suffix)) + suffix
            )
            cursor = last
        if end - index > 1:
            suffix = f" ×{end - index}"
            collapsed[-1] = (
                truncate(collapsed[-1], PREVIEW_LINE_MAX - len(suffix)) + suffix
            )
        output.extend(collapsed[: max(0, limit - len(output))])
        index = end
    return output


class _StderrSignatures:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.entries: list[str] = []
        self.current_block: list[str] = []
        self.previous_block: tuple[list[str], int] | None = None

    def push(self, line: str) -> None:
        if not line.strip():
            self._finish_block()
        else:
            self.current_block.append(line)

    def _finish_block(self) -> None:
        if not self.current_block:
            return
        block, self.current_block = self.current_block, []
        if self.previous_block is None:
            self.previous_block = (block, 1)
            return
        previous, count = self.previous_block
        if previous == block:
            self.previous_block = (previous, count + 1)
            return
        self._emit_block(previous, count)
        self.previous_block = (block, 1)

    def _emit_block(self, block: list[str], count: int) -> None:
        if len(self.entries) >= self.limit:
            return
        collapsed: list[str] = []
        index = 0
        while index < len(block):
            end = index + 1
            while end < len(block) and block[end] == block[index]:
                end += 1
            repeats = end - index
            suffix = f" ×{repeats}" if repeats > 1 else ""
            collapsed.append(
                truncate(block[index], PREVIEW_LINE_MAX - len(suffix)) + suffix
            )
            index = end
        visible = min(len(collapsed), self.limit - len(self.entries))
        for index, iter_line in enumerate(collapsed[:visible]):
            line = iter_line
            if index + 1 == visible and count > 1:
                suffix = f" ×{count}"
                line = truncate(iter_line, PREVIEW_LINE_MAX - len(suffix)) + suffix
            self.entries.append(line)

    def finish(self) -> list[str]:
        self._finish_block()
        if self.previous_block is not None:
            block, count = self.previous_block
            self._emit_block(block, count)
            self.previous_block = None
        return self.entries


def _section_rows(chunks: list[tuple[str, Chunk]]) -> tuple[list[tuple], int]:
    sections = []
    for index, (stream, chunk) in enumerate(chunks):
        match = re.fullmatch(r"(.*) \((\d+)/(\d+)\)", chunk.title)
        base = match.group(1) if match else None
        if (
            match is not None
            and base
            and sections
            and sections[-1][0] == stream
            and sections[-1][1] == base
            and sections[-1][3] == index - 1
        ):
            previous = sections[-1]
            sections[-1] = (
                stream,
                base,
                previous[2],
                index,
                previous[4],
                chunk.line_end,
                int(match.group(3)),
            )
        else:
            sections.append(
                (
                    stream,
                    base or chunk.title,
                    index,
                    index,
                    chunk.line_start,
                    chunk.line_end,
                    None,
                )
            )
    result = []
    for stream, iter_title, index, index_end, start, end, count in sections:
        title = iter_title
        if count is None:
            title = chunks[index][1].title
        result.append((stream, title, index, index_end, start, end, count))
    return result, len(result)


def _render(
    handle: str,
    label: str,
    size: int,
    stdout: str,
    stderr: str,
    chunks: list[tuple[str, Chunk]],
    redactions: int,
    exit_code: int | None,
    profile: Profile | None,
    *,
    quiet: bool = False,
    preview_config: dict | None = None,
    stdout_lines: list[str] | None = None,
    stderr_lines: list[str] | None = None,
) -> str:
    if quiet:
        return (
            f"varde: captured {size} bytes → handle {handle} ({len(chunks)} chunks)\n"
        )
    config = preview_config or {}
    out_lines = stdout.splitlines() if stdout_lines is None else stdout_lines
    err_lines = stderr.splitlines() if stderr_lines is None else stderr_lines
    head_count = int(config.get("preview_head", 20))
    tail_count = int(config.get("preview_tail", 10))
    section_limit = int(config.get("preview_sections", 25))
    sections, _ = _section_rows(chunks)
    out = (
        f"varde: captured {size:,} bytes → handle {handle} ({len(out_lines)} lines, "
        f"{len(chunks)} chunk{'s' if len(chunks) != 1 else ''})  label: "
        f"{json.dumps(label, ensure_ascii=False)}\n"
    )
    if exit_code is not None:
        out += f"varde-toz: exit code {exit_code}\n"
    if redactions:
        out += f"varde-toz: {redactions} secret-like value(s) redacted\n"
    shown = sections[:section_limit]
    if shown:
        out += "── sections ──────────────────────────────────────────\n"
        for stream, iter_title, index, index_end, start, end, count in shown:
            title = iter_title
            tag = " [stderr]" if stream == "stderr" else ""
            if count:
                title = f"{iter_title} ({count} parts)"
            display_index = f"{index}-{index_end}" if index != index_end else str(index)
            out += (
                f"{display_index:>7}  {truncate_middle(title, 48):<48} "
                f"L{start}-L{end}{tag}\n"
            )
        omitted = len(sections) - len(shown)
        if omitted:
            out += f"… {omitted} more section(s) omitted\n"
    if head_count and out_lines:
        head = out_lines[:head_count]
        out += f"── head ({len(head)} lines) ──────────────────────────────────\n"
        out += "".join(_preview_line(line) + "\n" for line in head)
    tail_start = max(head_count, len(out_lines) - tail_count)
    tail = out_lines[tail_start:] if len(out_lines) > head_count else []
    if tail:
        out += f"── tail ({len(tail)} lines) ──────────────────────────────────\n"
        out += "".join(_preview_line(line) + "\n" for line in tail)
    if err_lines:
        out += f"── stderr ({len(err_lines)} lines) ────────────────────────────────\n"
        out += "".join(line + "\n" for line in _collapse(err_lines, tail_count))
    diagnostics = _diagnostics(out_lines, err_lines)
    if diagnostics:
        out += "── diagnostics ───────────────────────────────────────\n"
        for stream, line, level, text in diagnostics:
            out += f"{stream} L{line} [{level}] {text}\n"
    vocab = distinctive(
        [chunk.body for stream, chunk in chunks if stream == "stdout"], 12
    )
    if vocab:
        out += f"terms: {', '.join(vocab)}\n"
    if profile and profile.preview_kind == "toc":
        for row in preview_toc(
            [chunk for _stream, chunk in chunks if _stream == "stdout"],
            out_lines,
            profile,
            handle,
        ):
            out += (
                f"{row['title']} ({row['items']} items) "
                f"L{row['line_start']}-L{row['line_end']}\n"
            )
            out += "".join(line + "\n" for line in row["lines"])
            out += (
                f"read: varde run query --handle {handle} "
                f"--lines {row['line_start']}:{row['line_end']}\n"
            )
        out += f'search: varde run query --handle {handle} "<term>"\n'
    else:
        out += (
            f'next: varde run query --handle {handle} "<query>"   |   '
            f"varde run query --handle {handle} --chunk N\n"
        )
    return out


def _profile_hookpoint(
    profile: Profile | None,
    store: Store,
    handle: str,
    label: str,
    stdout: str,
    stderr: str,
) -> tuple[str | None, list[tuple[str, str]]]:
    """Run a trusted profile script within the capture path's tighter limits."""
    if profile is None or profile.script is None:
        return None, []
    from varde_toz.runner.script import Limits, Outcome, run_detailed

    row = store.get_by_handle(handle)
    if row is None:
        return None, []
    result = run_detailed(
        profile.script,
        input_text=stdout,
        meta={
            "handle": handle,
            "label": label,
            "bytes": len(stdout.encode()) + len(stderr.encode()),
            "lines": len(stdout.splitlines()),
            "exitCode": row["exit_code"],
            "stream": "stdout",
        },
        limits=Limits(
            timeout_ms=1000, memory_bytes=64 * 1024 * 1024, max_output_bytes=4096
        ),
    )
    if result.outcome is not Outcome.OK:
        return None, []
    return result.output, result.records or []


def capture(
    input: CaptureInput,
    root: Path | None = None,
    store_path: Path | None = None,
    config: dict[str, object] | None = None,
) -> CaptureResult:
    if config is None:
        with _phase_span("config load"):
            config = load_config()
    with _phase_span("project-root resolution"):
        root = root or project_root()
    with _phase_span("capture policy and profile setup"):
        size = len(input.stdout) + len(input.stderr)
        threshold = (
            input.threshold
            if input.threshold is not None
            else config_int(config, "threshold", 4096)
        )
        if not input.force and size <= threshold:
            return CaptureResult(0, input.stdout.decode("utf-8", "replace"))
        source = input.source or input.label or "stdin"
        key = source_key(source)
        label = input.label or truncate(key, 120) or "stdin"
        normalized_key = input.label.strip() if input.label else key
        capture_rules = config.get("capture", {})
        capture_rules = capture_rules if isinstance(capture_rules, dict) else {}
        never_patterns = capture_rules.get("never", [])
        builtin_never = capture_rules.get("builtin_never", True)
        if never_capture(
            normalized_key, never_patterns, builtin_never
        ) or never_capture(source, never_patterns, builtin_never):
            return CaptureResult(
                0,
                (input.stdout + input.stderr).decode("utf-8", "replace"),
                "never-capture",
            )
        if looks_binary(input.stdout) or looks_binary(input.stderr):
            return CaptureResult(
                0, (input.stdout + input.stderr).decode("utf-8", "replace"), "binary"
            )
        profiles, _diagnostics = load_profiles(root)
        profile = find_match(profiles, source, _command_capture(input.kind))
        if profile and size > MAX_PROFILED_CAPTURE_BYTES:
            raise ValueError(
                f"profile-matched capture exceeds the "
                f"{MAX_PROFILED_CAPTURE_BYTES}-byte limit; "
                "reduce input or adjust the matching profile"
            )
    with _phase_span("capture redaction"):
        stdout = strip_ansi(input.stdout.decode("utf-8", "replace"))
        stderr = strip_ansi(input.stderr.decode("utf-8", "replace"))
        if (
            input.content_redacted
            and b"\x1b" not in input.stdout
            and b"\x1b" not in input.stderr
        ):
            redactions = 0
            redact_config = configured_redactor(root)
        else:
            redact_config = configured_redactor(root)
            stdout, redactions = redact_configured(stdout, redact_config)
            stderr, more = redact_configured(stderr, redact_config)
            redactions += more
    with _phase_span("chunking and preview"):
        stdout = _expand_minified_json(stdout)
        stdout_lines, stderr_lines = stdout.splitlines(), stderr.splitlines()
        all_chunks = [
            ("stdout", chunk)
            for chunk in (
                chunk_with_profile(stdout, profile, lines=stdout_lines)
                if profile
                else chunk_default(stdout, _lines=stdout_lines)
            )
        ]
        err_chunks = chunk_default(stderr, _lines=stderr_lines) if stderr else []
        all_chunks.extend(("stderr", chunk) for chunk in err_chunks)
    with _phase_span("metadata sanitization"):
        safe_label = metadata.sanitize_text(
            label, lambda text: redact_configured(text, redact_config)
        )
        safe_source = metadata.sanitize_text(
            source, lambda text: redact_configured(text, redact_config)
        )
    with _phase_span("project-root resolution"):
        path = store_path or store_db_path(root, config_dir())
    with _phase_span("SQLite open and pragmas"):
        store = Store(path)
    with store:
        with _phase_span("store transaction begin"):
            store.conn.execute("BEGIN")
        with store.conn:
            with _phase_span("store metadata and records"):
                key_id = identity_at(path.parent, normalized_key)
                capture = NewCapture(
                    safe_label,
                    input.kind,
                    safe_source,
                    key_id,
                    normalized_key,
                    size,
                    input.exit_code,
                    input.session,
                    redactions,
                    file_mtime=input.file_mtime,
                    file_hash=input.file_hash,
                )
            with _phase_span("FTS5 write"):
                handle = store.insert_capture(
                    capture, all_chunks, indexed=not input.defer_index
                )
            with _phase_span("store metadata and records"):
                row = store.get_by_handle(handle)
                script_output, records = _profile_hookpoint(
                    profile, store, handle, safe_label, stdout, stderr
                )
                store.insert_records(row["id"], records)
            preview_config = {
                key: config.get(key, default)
                for key, default in (
                    ("preview_head", 20),
                    ("preview_tail", 10),
                    ("preview_sections", 25),
                )
            }
            with _phase_span("output"):
                output = _render(
                    handle,
                    safe_label,
                    size,
                    stdout,
                    stderr,
                    all_chunks,
                    redactions,
                    input.exit_code,
                    profile,
                    quiet=input.quiet,
                    preview_config=preview_config,
                    stdout_lines=stdout_lines,
                    stderr_lines=stderr_lines,
                )
            if script_output:
                header = output.split("\n", 1)[0] + "\n"
                output = (
                    header
                    + script_output
                    + ("" if script_output.endswith("\n") else "\n")
                    + (
                        f'next: varde run query --handle {handle} "<query>"   |   '
                        f"varde run query --handle {handle} --chunk N\n"
                    )
                )
            with _phase_span("statistics write"):
                store.conn.execute(
                    STATS_LOG_INSERT,
                    (input.kind, size, len(output.encode()), input.session),
                )
    return CaptureResult(1, output)


def capture_spooled(
    input_file: BinaryIO,
    size: int,
    input: CaptureInput,
    root: Path | None = None,
    stream_name: str = "stdout",
    store_path: Path | None = None,
) -> tuple[int, str]:
    """Capture a large unprofiled stream with bounded memory and disk-backed text
    staging.
    """
    config = load_config()
    root = root or project_root()
    threshold = (
        input.threshold
        if input.threshold is not None
        else config_int(config, "threshold", 4096)
    )
    if not input.force and size <= threshold:
        return 0, ""
    source = input.source or input.label or "stdin"
    key = source_key(source)
    label = input.label or truncate(key, 120) or "stdin"
    normalized_key = input.label.strip() if input.label else key
    capture_rules = config.get("capture", {})
    capture_rules = capture_rules if isinstance(capture_rules, dict) else {}
    rules = capture_rules.get("never", [])
    if never_capture(
        normalized_key, rules, capture_rules.get("builtin_never", True)
    ) or never_capture(source, rules, capture_rules.get("builtin_never", True)):
        return 0, ""
    input_file.seek(0)
    sample = input_file.read(8192)
    if looks_binary(sample):
        return 0, ""
    profiles, _ = load_profiles(root)
    profile = find_match(profiles, source, _command_capture(input.kind))
    if profile:
        if size > MAX_PROFILED_CAPTURE_BYTES:
            raise ValueError(
                f"profile-matched capture exceeds the "
                f"{MAX_PROFILED_CAPTURE_BYTES}-byte limit; "
                "reduce input or adjust the matching profile"
            )
        input_file.seek(0)
        result = capture(
            CaptureInput(
                input_file.read(),
                b"",
                input.label,
                source,
                input.kind,
                input.exit_code,
                input.session,
                input.force,
                input.defer_index,
                input.threshold,
                input.quiet,
            ),
            root,
        )
        return result.status, result.output
    input_file.seek(0)
    redactor = configured_redactor(root)
    with tempfile.TemporaryFile(mode="w+b") as sanitized:
        redactions = normalize_and_redact(input_file, sanitized, redactor)
        sanitized.seek(0)
        safe_label = metadata.sanitize_text(
            label, lambda text: redact_configured(text, redactor)
        )
        safe_source = metadata.sanitize_text(
            source, lambda text: redact_configured(text, redactor)
        )
        path = store_path or store_db_path(root, config_dir())
        with Store(path) as store:
            store.conn.execute("BEGIN")
            with store.conn:
                private_key = identity_at(path.parent, normalized_key)
                capture_row = NewCapture(
                    safe_label,
                    input.kind,
                    safe_source,
                    private_key,
                    normalized_key,
                    size,
                    input.exit_code,
                    input.session,
                    redactions,
                )
                stream_state = {
                    "stream": stream_name,
                    "lines": 0,
                    "stderr_lines": 0,
                    "chunks": 0,
                    "sections": [],
                    "sections_omitted": 0,
                    "head": [],
                    "tail": [],
                    "diagnostics": [],
                    "stderr_signatures": _StderrSignatures(
                        config_int(config, "preview_tail", 10)
                    ),
                }

                def chunks() -> Iterator[tuple[str, Chunk]]:
                    yield from _stored_stream_chunks(sanitized, stream_state, config)

                handle = store.insert_capture(
                    capture_row, chunks(), indexed=not input.defer_index
                )
                output = _render_streamed(
                    handle,
                    safe_label,
                    size,
                    input.exit_code,
                    redactions,
                    stream_state,
                    config,
                )
                store.conn.execute(
                    STATS_LOG_INSERT,
                    (input.kind, size, len(output.encode()), input.session),
                )
        return 1, output


def _stored_stream_chunks(
    source: BinaryIO, state: dict, config: dict
) -> Iterator[tuple[str, Chunk]]:
    section_limit = int(config.get("preview_sections", 25))
    tail_limit = int(config.get("preview_tail", 10))
    for offset, block in line_blocks(source):
        for index, line in enumerate(block, offset + 1):
            state["stderr_lines" if state["stream"] == "stderr" else "lines"] = index
            if state["stream"] == "stdout":
                if len(state["head"]) < int(config.get("preview_head", 20)):
                    state["head"].append(_preview_line(line))
                elif tail_limit:
                    state["tail"].append(_preview_line(line))
                    if len(state["tail"]) > tail_limit:
                        state["tail"].pop(0)
            else:
                state["stderr_signatures"].push(line)
            level = _diagnostic_level(line)
            if level and (
                len(state["diagnostics"]) < PREVIEW_DIAGNOSTICS or level == "error"
            ):
                item = (index, level, _preview_line(line))
                if len(state["diagnostics"]) < PREVIEW_DIAGNOSTICS:
                    state["diagnostics"].append(item)
                elif level == "error":
                    warning = next(
                        (
                            i
                            for i, old in enumerate(state["diagnostics"])
                            if old[1] == "warning"
                        ),
                        None,
                    )
                    if warning is not None:
                        state["diagnostics"].pop(warning)
                        state["diagnostics"].append(item)
        yield _stream_chunk(block, offset, state, section_limit)


def _stream_chunk(
    lines: list[str], offset: int, state: dict, section_limit: int
) -> tuple[str, Chunk]:
    index = state["chunks"]
    chunk = Chunk(
        index,
        truncate(next((line.strip() for line in lines if line.strip()), ""), 72),
        offset + 1,
        offset + len(lines),
        classify(lines),
        "\n".join(lines),
    )
    if len(state["sections"]) < section_limit:
        state["sections"].append((index, chunk.title, chunk.line_start, chunk.line_end))
    else:
        state["sections_omitted"] += 1
    state["chunks"] += 1
    return state["stream"], chunk


def _render_streamed(
    handle: str,
    label: str,
    size: int,
    exit_code: int | None,
    redactions: int,
    state: dict,
    config: dict,
) -> str:
    stderr_head = state["stderr_signatures"].finish()
    out = (
        f"varde: captured {size:,} bytes → handle {handle} ({state['lines']} lines, "
        f"{state['chunks']} chunk{'s' if state['chunks'] != 1 else ''})  label: "
        f"{json.dumps(label, ensure_ascii=False)}\n"
    )
    if exit_code is not None:
        out += f"varde-toz: exit code {exit_code}\n"
    if redactions:
        out += f"varde-toz: {redactions} secret-like value(s) redacted\n"
    out += "varde-toz: streamed text; fixed-size sections, normalized line endings\n"
    if state["sections"]:
        out += "── sections ──────────────────────────────────────────\n"
        for index, title, start, end in state["sections"]:
            tag = " [stderr]" if state["stream"] == "stderr" else ""
            out += (
                f"{index:>7}  {truncate_middle(title, 48):<48} L{start}-L{end}{tag}\n"
            )
        if state["sections_omitted"]:
            out += f"     … {state['sections_omitted']} more\n"
    if state["head"]:
        out += (
            f"── head ({len(state['head'])} lines) ──────────────────────────────────\n"
        )
        out += "".join(line + "\n" for line in state["head"])
    if state["tail"] and state["lines"] > len(state["head"]):
        out += (
            f"── tail ({len(state['tail'])} lines) ──────────────────────────────────\n"
        )
        out += "".join(line + "\n" for line in state["tail"])
    if state["stderr_lines"] and stderr_head:
        out += (
            f"── stderr ({state['stderr_lines']} lines) "
            "────────────────────────────────\n"
        )
        out += "".join(line + "\n" for line in stderr_head)
    if state["diagnostics"]:
        out += "── diagnostics ───────────────────────────────────────\n"
        out += "".join(
            f"{state['stream']} L{line} [{level}] {text}\n"
            for line, level, text in state["diagnostics"]
        )
    return (
        out + f'next: varde run query --handle {handle} "<query>"   |   '
        f"varde run query --handle {handle} --chunk N\n"
    )


def _expand_minified_json(text: str) -> str:
    trimmed = text.strip()
    if len(trimmed.splitlines()) > 2 or not trimmed.startswith(("{", "[")):
        return text
    try:
        value = json.loads(trimmed)
        return json.dumps(_sort_json(value), indent=2, ensure_ascii=False)
    except ValueError:
        return text


def _sort_json(value):
    if isinstance(value, dict):
        return {key: _sort_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sort_json(item) for item in value]
    return value
