"""Run JavaScript against a captured Toz stream."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn, cast

from varde_toz.config import config_int


def _raise_validation(error: Exception) -> NoReturn:
    raise error


HELP = """Run a QuickJS script and capture its command output

Usage: varde run run [OPTIONS]

Options:
      --fallback-dir <FALLBACK_DIR>
          External store to try after primary-store access fails

      --script <SCRIPT>
          Run a QuickJS batch script from a file, or `-` for stdin

      --code <CODE>
          Run an inline QuickJS batch script

      --project <PROJECT>
          Project directory (default: git root of cwd, else cwd)

      --handle <HANDLE>
          Capture to read from the script

      --json
          Machine-readable JSON output

      --quiet
          Print only the handle line on overflow

      --stream <STREAM>
          Capture stream to read (stdout | stderr)
          [default: stdout]

      --partial
          Permit computation over an unfinished capture

      --timeout-ms <TIMEOUT_MS>
          Script wall-clock limit in milliseconds (default 5000)

      --memory-mb <MEMORY_MB>
          Script heap limit in MB

  -l, --label <LABEL>
          Human label for the capture (also the supersession key)

  -h, --help
          Print help (see a summary with '-h')

Example:
  varde run run --script - <<'JS'
  const result = vardeToz.exec({argv: ['/bin/ls', '-la']});
  print(result.exitCode, result.capture.preview || result.stdout);
  JS

Use --code '<js>' for an inline script. Scripts can call print(),
console.log(), and console.error(). The vardeToz API provides exec({argv | shell,
cwd?, env?, timeoutMs?, capture?, raw?}), eachLine(fn) or eachLine(stream, fn),
text() or text(stream), and handle metadata (handle, label, bytes, lines,
exitCode, stream). Use eachLine for large captures; text has a size limit.

Command output up to the capture threshold (maximum 64 KiB) is complete in
stdout/stderr with capture.state "inline". Larger output has a preview and
capture.handle. capture: true forces retention; raw: true retains raw bytes;
never-capture rules override both. Script print output appears inline until its
output limit, then the normal preview and handle are returned. Pass --handle H
to analyze an existing capture; --stream stderr selects its stderr stream, and
--partial permits reading an unfinished capture.
"""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--script")
    parser.add_argument("--code")
    parser.add_argument("--project")
    parser.add_argument("--fallback-dir")
    parser.add_argument("--handle")
    parser.add_argument("--stream", default="stdout")
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--timeout-ms", type=_nonnegative_int)
    parser.add_argument("--memory-mb", type=_nonnegative_int)
    parser.add_argument("-l", "--label")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    if "--help" in argv or "-h" in argv:
        print(
            HELP.replace(
                "          [default: stdout]",
                " " * 10 + "\n          [default: stdout]",
            ),
            end="",
        )
        return 0
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code is None else int(exc.code)
    if bool(args.code is not None) == bool(args.script is not None):
        if args.code is None and args.script is None:
            options = []
            if args.handle:
                options.extend(("--handle", "<HANDLE>"))
            if args.stream != "stdout":
                options.extend(("--stream", "<STREAM>"))
            if args.partial:
                options.append("--partial")
            usage = "varde run run " + " ".join(options + ["--script <SCRIPT>"])
            print(
                (
                    "error: the following required arguments were not provided:\n"
                    "  --script <SCRIPT>\n\n"
                    f"Usage: {usage}\n\nFor more information, try '--help'."
                ),
                file=sys.stderr,
            )
            return 2
        parser.error("the argument --code cannot be used with --script")
    try:
        source = (
            args.code
            if args.code is not None
            else (
                sys.stdin.read()
                if args.script == "-"
                else Path(args.script).read_text()
            )
        )
        if not source.strip():
            _raise_validation(
                ValueError(
                    "empty script; pass --script - with a heredoc, or "
                    "--code '<js>' for a one-liner"
                )
            )
        return _execute(args, source)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"varde-toz: {exc}", file=sys.stderr)
        return 2


def _execute(args, source: str) -> int:
    # Keep Wasmtime off every non-script path.
    import blake3

    from varde_toz.config import config_dir, load_config
    from varde_toz.project import project_root, store_db_path
    from varde_toz.runner.script import Limits, Outcome, run_detailed
    from varde_toz.store import Store

    config = load_config()
    root = Path(
        args.project or os.environ.get("TOZ_PROJECT") or project_root()
    ).resolve()
    store_path = store_db_path(root, config_dir())
    text = ""
    meta: dict = {"stream": args.stream}
    if args.handle:
        if not store_path.exists():
            raise ValueError(f"no capture with handle {args.handle}")
        with Store.open(store_path) as store:
            row = store.get_by_handle(args.handle)
            if row is None:
                raise ValueError(f"no capture with handle {args.handle}")
            if row["state"] == "running" and not args.partial:
                raise ValueError(
                    f"capture {args.handle} is still running; wait for it to "
                    "finish, or pass --partial to compute over what has been "
                    "committed so far"
                )
            text = store.full_text(row["id"], args.stream)
            if store.line_count(row["id"], args.stream):
                text += "\n"
            meta.update(
                {
                    "handle": row["handle"],
                    "label": row["label"],
                    "bytes": row["bytes"],
                    "lines": store.line_count(row["id"], args.stream),
                    "exitCode": row["exit_code"],
                }
            )

    script_cfg = config.get("script", {})
    script_cfg = script_cfg if isinstance(script_cfg, dict) else {}
    if script_cfg.get("enabled", True) is False:
        raise ValueError(
            "varde run is disabled (set script.enabled = true in config.toml)"
        )
    limits = Limits(
        timeout_ms=args.timeout_ms
        if args.timeout_ms is not None
        else config_int(script_cfg, "timeout_ms", 5000),
        memory_bytes=(
            args.memory_mb
            if args.memory_mb is not None
            else config_int(script_cfg, "memory_mb", 64)
        )
        * 1024
        * 1024,
        max_output_bytes=config_int(script_cfg, "max_output_bytes", 1024 * 1024),
        max_text_bytes=config_int(script_cfg, "max_text_bytes", 16 * 1024 * 1024),
    )

    def exec_command(request: dict, remaining: float) -> dict:
        if not isinstance(request, dict) or not (
            isinstance(request.get("argv"), list)
            or isinstance(request.get("shell"), str)
        ):
            raise ValueError("exec request must include argv or shell")
        child_env = os.environ.copy()
        if isinstance(request.get("env"), dict):
            child_env.update(
                {str(key): str(value) for key, value in request["env"].items()}
            )
        command = (
            request.get("argv")
            if isinstance(request.get("argv"), list)
            else request["shell"]
        )
        use_shell = isinstance(command, str)
        shell_source = command if use_shell else None
        if use_shell:
            command = [child_env.get("SHELL", "/bin/sh"), "-c", command]
        if isinstance(command, list) and (
            not command or not all(isinstance(item, str) for item in command)
        ):
            raise ValueError("exec argv must be a nonempty array of strings")
        command = cast("list[str]", command)
        cwd = Path(request.get("cwd", root))
        if not cwd.is_absolute():
            cwd = root / cwd
        try:
            timeout = min(
                remaining, float(request.get("timeoutMs", remaining * 1000)) / 1000
            )
            try:
                completed = subprocess.run(  # noqa: S603 - Runs the caller's explicitly requested child command with shell disabled.
                    command,
                    shell=False,
                    cwd=cwd,
                    env=child_env,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
                stdout_bytes, stderr_bytes = completed.stdout, completed.stderr
                exit_code, timed_out = completed.returncode, False
            except subprocess.TimeoutExpired as exc:
                stdout_bytes, stderr_bytes = exc.stdout or b"", exc.stderr or b""
                exit_code, timed_out = None, True
            total_bytes = len(stdout_bytes) + len(stderr_bytes)
            if total_bytes > 8 * 1024 * 1024:
                raise ValueError("command output exceeded the 8388608-byte limit")
            source_key = shell_source if shell_source is not None else " ".join(command)
            force_capture = bool(request.get("capture") or request.get("raw"))
            preview_cap = min(config_int(config, "threshold", 64 * 1024), 64 * 1024)
            truncated = total_bytes > preview_cap
            stdout_preview = stdout_bytes[:preview_cap].decode("utf-8", "replace")
            stderr_preview = stderr_bytes[
                : max(0, preview_cap - min(len(stdout_bytes), preview_cap))
            ].decode("utf-8", "replace")
            capture_info: dict = {"state": "inline"}
            raw_info: dict = {"state": "not_requested"}
            if force_capture or total_bytes > preview_cap:
                from varde_toz.capture import CaptureInput, capture

                capture_result = capture(
                    CaptureInput(
                        stdout_bytes,
                        stderr_bytes,
                        source_key,
                        source_key,
                        "exec",
                        exit_code,
                        force=force_capture,
                        threshold=preview_cap,
                    ),
                    root,
                )
                stored, capture_preview = capture_result.status, capture_result.output
                if stored:
                    match = re.search(r"handle ([a-z0-9_-]+)", capture_preview)
                    capture_info = {
                        "state": "captured",
                        "handle": match.group(1) if match else None,
                        "preview": capture_preview,
                    }
                elif force_capture:
                    capture_info = {"state": "excluded", "rule": "never-capture"}
                    stdout_preview, stderr_preview = (
                        stdout_bytes.decode("utf-8", "replace"),
                        stderr_bytes.decode("utf-8", "replace"),
                    )
            if request.get("raw"):
                from varde_toz.raw import RawStore

                raw_cfg = config.get("raw", {})
                raw_cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
                if capture_info["state"] == "excluded":
                    raw_info = {"state": "excluded"}
                elif not raw_cfg.get("enabled", False):
                    raw_info = {"state": "disabled"}
                else:
                    raw_handle = RawStore(
                        config_dir() / "raw",
                        enabled=bool(raw_cfg.get("enabled", False)),
                        max_bytes=int(raw_cfg.get("max_bytes", 1_000_000)),
                    ).store(source_key, stdout_bytes, stderr_bytes)
                    raw_info = {"state": "stored", "handle": str(raw_handle)}
            result = {
                "exitCode": exit_code,
                "signal": None,
                "timedOut": timed_out,
                "interrupted": False,
                "stdout": stdout_preview,
                "stderr": stderr_preview,
                "truncated": truncated,
                "capture": capture_info,
                "raw": raw_info,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "exitCode": None,
                "signal": None,
                "timedOut": True,
                "interrupted": False,
                "stdout": (exc.stdout or b"").decode("utf-8", "replace"),
                "stderr": (exc.stderr or b"").decode("utf-8", "replace"),
                "truncated": False,
                "capture": {"state": "inline"},
                "raw": {"state": "not_requested"},
            }
        else:
            return result

    result = run_detailed(
        source, input_text=text, meta=meta, limits=limits, command=exec_command
    )
    if result.outcome is not Outcome.OK:
        messages = {
            Outcome.EXCEPTION: (
                1,
                (
                    f"varde-toz: script error: "
                    f"{result.error or 'script raised an exception'}"
                ),
            ),
            Outcome.TIMEOUT: (
                3,
                (
                    f"varde-toz: script exceeded {limits.timeout_ms}ms; narrow "
                    "the computation or raise --timeout-ms"
                ),
            ),
            Outcome.MEMORY_LIMIT: (
                4,
                (
                    f"varde-toz: script exceeded "
                    f"{limits.memory_bytes // (1024 * 1024)}MB; prefer "
                    "vardeToz.eachLine() over vardeToz.text(), or raise "
                    "--memory-mb"
                ),
            ),
            Outcome.OUTPUT_LIMIT: (
                5,
                (
                    f"varde-toz: script printed more than "
                    f"{limits.max_output_bytes} bytes; aggregate further before "
                    "printing"
                ),
            ),
            Outcome.RECORD_LIMIT: (
                6,
                (
                    "varde-toz: script exceeded the record limit "
                    f"({10_000} records or {8 * 1024 * 1024} serialized bytes); "
                    "reduce toz.record() output"
                ),
            ),
        }
        code, message = messages[result.outcome]
        print(message, file=sys.stderr)
        return code
    if result.records and args.handle:
        with Store.open(store_path) as store:
            row = store.get_by_handle(args.handle)
            store.insert_records(row["id"], result.records)
    output = result.output
    threshold = config_int(config, "threshold", 4096)
    if len(output.encode()) <= threshold:
        sys.stdout.write(output)
        return 0
    from varde_toz.capture import CaptureInput, capture

    fingerprint = blake3.blake3(source.encode()).hexdigest()[:12]
    origin = f"varde run {args.handle or 'no-capture'} #{fingerprint}"
    capture_result = capture(
        CaptureInput(
            output.encode(),
            b"",
            args.label,
            origin,
            "script",
            0,
            force=True,
            quiet=args.quiet and not args.json,
        ),
        root,
    )
    status, preview = capture_result.status, capture_result.output
    if not status:
        sys.stdout.write(output)
        return 0
    handle = _last_handle(preview)
    if args.json:
        print(
            json.dumps(
                _script_preview_json(store_path, handle, preview),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    elif args.quiet and handle:
        with Store.open(store_path) as store:
            row = store.get_by_handle(handle)
            print(
                f"varde: captured {row['bytes']:,} bytes → handle {handle} "
                f"({row['chunk_count']} chunks)"
            )
    else:
        sys.stdout.write(preview)
    return 0


def _last_handle(preview: str) -> str | None:
    match = re.search(r"handle ([a-z0-9_-]+)", preview)
    return match.group(1) if match else None


def _nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _script_preview_json(store_path: Path, handle: str | None, preview: str) -> dict:
    if handle is None:
        return {"handle": None, "preview": preview}
    from varde_toz.capture import _diagnostics, _preview_line, _section_rows
    from varde_toz.chunk import Chunk
    from varde_toz.config import load_config
    from varde_toz.store import Store
    from varde_toz.terms import distinctive

    with Store.open(store_path) as store:
        row = store.get_by_handle(handle)
        stored_chunks = store.chunks_for(row["id"])
        chunks = [
            (
                chunk["stream"],
                Chunk(
                    int(chunk["ordinal"]),
                    chunk["title"],
                    int(chunk["line_start"]),
                    int(chunk["line_end"]),
                    chunk["content_type"],
                    chunk["body"],
                ),
            )
            for chunk in stored_chunks
        ]
        sections, _ = _section_rows(chunks)
        config = load_config()
        section_limit = config_int(config, "preview_sections", 25)
        head_limit = config_int(config, "preview_head", 20)
        tail_limit = config_int(config, "preview_tail", 10)
        stdout = store.full_text(row["id"], "stdout")
        stderr = store.full_text(row["id"], "stderr")
        out_lines, err_lines = stdout.splitlines(), stderr.splitlines()
        section_values = []
        for stream, title, index, index_end, line_start, line_end, _count in sections[
            :section_limit
        ]:
            item = {
                "index": index,
                "stream": stream,
                "title": title,
                "line_start": line_start,
                "line_end": line_end,
            }
            if index_end != index:
                item["index_end"] = index_end
            section_values.append(item)
        return {
            "handle": handle,
            "label": row["label"],
            "bytes": row["bytes"],
            "chunks": len(stored_chunks),
            "exit_code": row["exit_code"],
            "redactions": row["redactions"],
            "binary": bool(row["binary"]),
            "streamed": False,
            "sections": section_values,
            "sections_omitted": max(0, len(sections) - section_limit),
            "head": [_preview_line(line) for line in out_lines[:head_limit]],
            "tail": [
                _preview_line(line)
                for line in out_lines[max(head_limit, len(out_lines) - tail_limit) :]
            ]
            if len(out_lines) > head_limit
            else [],
            "stderr_lines": len(err_lines),
            "stderr_head": [_preview_line(line) for line in err_lines[:head_limit]],
            "diagnostics": [
                {"stream": stream, "line": line, "level": level, "text": text}
                for stream, line, level, text in _diagnostics(out_lines, err_lines)
            ],
            "lines": len(out_lines),
            "terms": distinctive(
                [chunk.body for stream, chunk in chunks if stream == "stdout"], 12
            ),
            "toc": None,
            "script_output": None,
            "preview": preview,
        }
